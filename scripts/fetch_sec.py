"""
fetch_sec.py — pull SEC 8-K cyber-incident filings and classify them into the schema.

Uses EDGAR full-text search to find 8-K filings with Item 1.05 (material
cybersecurity incidents, mandatory since Dec 2023), fetches each filing, and runs
it through the same LLM classifier as ingest.py. Best source for the FINANCIAL
IMPACT and DOWNTIME fields — public companies disclose real numbers here.

Note on attackers: 8-Ks frequently do NOT name the ransomware group ("unauthorized
third party"). So `group` often comes back "not publicly disclosed". Enrich it by
cross-referencing the victim against ransomware.live afterwards (see --note).

SEC requires a descriptive User-Agent with contact info. Set SEC_USER_AGENT, e.g.
  export SEC_USER_AGENT="Your Name your@email.com"

Setup:  pip install -r requirements.txt ; set OPENAI_API_KEY

Usage:
  python scripts/fetch_sec.py --since 2024-01-01 --limit 10 --dry-run
  python scripts/fetch_sec.py --since 2024-01-01 --until 2025-01-01 --limit 25
  python scripts/fetch_sec.py --query '"Item 1.05" ransomware' --limit 15
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import extract, ingest_record  # reuse the classifier + append logic

EFTS = "https://efts.sec.gov/LATEST/search-index"
UA = os.environ.get("SEC_USER_AGENT", "CNA Ransomware Research research@example.com")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}


def _opt(args, name, default=None):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def _get(url: str) -> bytes:
    import gzip
    r = urlopen(Request(url, headers=HEADERS), timeout=60)
    data = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
    return data


def search(query: str, since: str, until: str, page_size: int = 100) -> list[dict]:
    """EDGAR full-text search for 8-K filings matching the query in a date range."""
    hits, frm = [], 0
    while True:
        url = (f"{EFTS}?q={quote(query)}&forms=8-K"
               f"&startdt={since}&enddt={until}&from={frm}")
        payload = json.loads(_get(url))
        batch = payload.get("hits", {}).get("hits", [])
        hits.extend(batch)
        total = payload.get("hits", {}).get("total", {}).get("value", 0)
        frm += len(batch)
        if frm >= total or not batch or frm >= 300:
            break
        time.sleep(0.3)  # be polite to SEC
    return hits


def doc_url(hit: dict) -> str | None:
    """Build the primary-document URL from a search hit."""
    src = hit.get("_source", {})
    adsh = src.get("adsh")                       # e.g. 0001043509-24-000063
    ciks = src.get("ciks") or []
    fname = hit.get("_id", "").split(":", 1)[-1]  # e.g. sah-20240705.htm
    if not (adsh and ciks and fname):
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{int(ciks[0])}/{adsh.replace('-', '')}/{fname}"


def victim_name(hit: dict) -> str:
    names = hit.get("_source", {}).get("display_names") or [""]
    return names[0].split("  (")[0].strip()


# --- attacker enrichment from ransomware.live -------------------------------
import re
from pathlib import Path

_SUFFIX = re.compile(r"\b(inc|inc\.|corp|corp\.|corporation|co|co\.|company|ltd|llc|l\.l\.c|plc|the|group|holdings|international)\b", re.I)


def _norm(name: str) -> str:
    n = _SUFFIX.sub(" ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def load_group_index() -> dict:
    """norm(victim) -> group, from the ransomware.live pulls (data/raw). 8-Ks
    rarely name the attacker; this recovers it by victim-name match."""
    idx, raw = {}, Path(__file__).resolve().parent.parent / "data" / "raw"
    if not raw.exists():
        return idx
    for f in raw.glob("sector_*.json"):
        try:
            recs = json.loads(f.read_text(encoding="utf-8").lstrip("﻿"))
        except Exception:
            continue
        for v in recs if isinstance(recs, list) else []:
            k = _norm(v.get("victim", ""))
            if k and v.get("group") and k not in idx:
                idx[k] = v["group"]
    return idx


def enrich_attacker(rec: dict, gidx: dict) -> bool:
    """Fill the group from ransomware.live when the filing didn't name it. A
    match also confirms it was a leak-site ransomware victim, so a vague
    'other-cyber' classification is upgraded to 'ransomware'."""
    have = (rec.get("group") or "").strip().lower()
    if have and have not in ("not publicly disclosed", "unknown", "n/a", ""):
        return False
    # Exact normalized match only — loose substring matching produced false
    # positives (short names match everything). Precision over recall here.
    grp = gidx.get(_norm(rec.get("victim", "")))
    if grp:
        rec["group"] = grp
        if rec.get("incident_type") == "other-cyber":
            rec["incident_type"] = "ransomware"
        return True
    return False


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    query = _opt(args, "--query", '"Item 1.05"')
    since = _opt(args, "--since", "2023-12-01")
    until = _opt(args, "--until", date.today().isoformat())
    limit = int(_opt(args, "--limit", "10"))

    print(f"searching EDGAR: q={query!r} forms=8-K {since}..{until}")
    hits = search(query, since, until)
    gidx = load_group_index()
    print(f"found {len(hits)} filings; classifying up to {limit} "
          f"(attacker index: {len(gidx)} ransomware.live victims)\n")

    counts = {}
    processed = 0
    for hit in hits:
        if processed >= limit:
            break
        url = doc_url(hit)
        if not url:
            continue
        vic = victim_name(hit)
        processed += 1
        enriched = False
        try:
            from ingest import strip_html
            text = strip_html(_get(url).decode("utf-8", "replace"))[:12000]
            rec = extract(text, url)
            enriched = enrich_attacker(rec, gidx)
            status = ingest_record(rec, dry)
        except Exception as e:
            status = f"error:{str(e)[:60]}"
        counts[status.split(":")[0]] = counts.get(status.split(":")[0], 0) + 1
        flag = {"added": "+", "dry": "~", "error": "!"}.get(status.split(":")[0], "-")
        extra = (f" -> {rec['industry']}"
                 + (f" [group: {rec['group']}{' *enriched' if enriched else ''}]"
                    if rec.get("group") and rec["group"].lower() != "not publicly disclosed" else "")
                 ) if status in ("added", "dry") else ""
        print(f"  {flag} [{status}] {vic}{extra}")
        time.sleep(0.3)  # SEC rate limit + gentle on the LLM

    print(f"\n{'[dry-run] ' if dry else ''}processed {processed}: " +
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if counts.get("added"):
        print("\nRebuild to propagate:\n"
              "  node scripts/export_mongo.js && python scripts/load_mongo.py\n"
              "  node scripts/export_graph.js   # then reload load.cypher + python scripts/embed_graph.py")
        print("\nTip: 8-Ks rarely name the group. Enrich `group` by matching these victims\n"
              "against ransomware.live (data/raw/) by name.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
