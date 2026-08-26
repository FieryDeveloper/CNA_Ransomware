"""
fetch_ransomwhere.py — on-chain ransom-PAID data, aggregated per group.

SEC filings and most leak sites don't reveal ransom paid, so this pulls the
Ransomwhere open dataset (https://ransomwhe.re) — crowdsourced ransomware payment
addresses tracked on-chain. It is keyed by crypto address + `family`, NOT by
victim, so it answers "how much has group X been paid" (real dollars), not "what
did company Y pay". That group-level ransom economics is a dimension we otherwise
have no data for.

Output: data/mongo/groups.json — one doc per ransomware family with total USD
paid, payment count, and date span, mapped to our group tokens where possible.
Loaded by load_mongo.py into the `groups` collection and surfaced by the entity
lane (ask.py "tell me about Conti" -> includes on-chain paid).

Usage:
  python scripts/fetch_ransomwhere.py            # -> data/mongo/groups.json
  python scripts/fetch_ransomwhere.py --dry-run  # print summary only
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

EXPORT = "https://api.ransomwhe.re/export"
OUT = Path(__file__).resolve().parent.parent / "data" / "mongo" / "groups.json"

# Ransomwhere family name -> our group token (from ransomware.live). Only the
# ones whose names differ; others match on the normalized name directly.
FAMILY_ALIAS = {
    "blackcat": "alphv", "revil sodinokibi": "revil", "netwalker mailto": "netwalker",
    "medusalocker": "medusalocker", "lockbit": "lockbit", "conti": "conti",
    "hive": "hive", "blacksuit": "blacksuit", "royal": "royal", "cuba": "cuba",
    "ryuk": "ryuk", "clop": "clop", "play": "play", "akira": "akira",
    "blackbasta": "blackbasta", "black basta": "blackbasta",
}


def norm(name: str) -> str:
    n = re.sub(r"\(.*?\)", " ", name or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def group_token(family: str) -> str:
    key = norm(family).replace(" ", "")
    spaced = norm(family)
    return FAMILY_ALIAS.get(spaced) or FAMILY_ALIAS.get(key) or key


def main() -> int:
    dry = "--dry-run" in sys.argv
    print(f"fetching {EXPORT} ...")
    raw = urlopen(Request(EXPORT, headers={"User-Agent": "cna-ransomware-research/1.0"}), timeout=60).read()
    recs = json.loads(raw).get("result", [])
    print(f"{len(recs)} payment addresses")

    agg = defaultdict(lambda: {"usd": 0.0, "payments": 0, "first": None, "last": None, "addresses": 0})
    unlabeled = 0.0
    for r in recs:
        fam = r.get("family") or "Unlabeled"
        if fam.lower() == "unlabeled":
            unlabeled += sum((t.get("amountUSD") or 0) for t in r.get("transactions", []))
            continue
        a = agg[fam]
        a["addresses"] += 1
        for t in r.get("transactions", []):
            a["usd"] += t.get("amountUSD") or 0
            a["payments"] += 1
            ts = t.get("time")
            if ts:
                d = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                a["first"] = min(a["first"], d) if a["first"] else d
                a["last"] = max(a["last"], d) if a["last"] else d

    docs = []
    for fam, a in agg.items():
        if a["usd"] <= 0:
            continue
        docs.append({
            "_id": group_token(fam),
            "family": fam,
            "ransom_paid_usd": round(a["usd"], 2),
            "payments": a["payments"],
            "addresses": a["addresses"],
            "first_payment": a["first"],
            "last_payment": a["last"],
            "source": "ransomwhere.re",
        })
    docs.sort(key=lambda d: -d["ransom_paid_usd"])

    total = sum(d["ransom_paid_usd"] for d in docs)
    print(f"\ngroups with tracked payments: {len(docs)}")
    print(f"total attributed ransom paid: ${total/1e6:.1f}M "
          f"(+ ${unlabeled/1e6:.1f}M unattributed)")
    print("\ntop groups by ransom paid:")
    for d in docs[:10]:
        print(f"  {d['family']:26} ${d['ransom_paid_usd']/1e6:8.2f}M  "
              f"({d['payments']} payments)  -> token '{d['_id']}'")

    if dry:
        print("\n[dry-run] not written.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(docs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {len(docs)} groups -> {OUT}")
    print("load with: python scripts/load_mongo.py   (add 'groups' to COLLECTIONS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
