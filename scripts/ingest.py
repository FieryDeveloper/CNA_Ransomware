"""
ingest.py — classify raw incident text into our schema and add it to the dataset.

Takes free text (an SEC 8-K, a news article, a breach notice), uses an LLM to
EXTRACT the fields our incidents use and CLASSIFY it into one of our 14
industries, then appends it to data/industries.json — the single source of truth
the whole pipeline derives from. After ingesting, the standard rebuild propagates
it to Mongo and the graph.

Design choices:
  - industries.json stays the master. We do NOT write straight to Mongo/Neo4j,
    so there is one place data lives and the derived stores never drift.
  - The LLM is constrained to our exact industry list (enum) and told to write
    "not publicly disclosed" rather than guess a missing figure — same honesty
    rule the original research used.
  - Dollar parsing is left to export_mongo.js on rebuild, so there is one parser.

Setup:  pip install -r requirements.txt ; set OPENAI_API_KEY (in .env is fine)

Usage:
  python scripts/ingest.py --file article.txt
  python scripts/ingest.py --url https://www.sec.gov/...    # fetches + strips HTML
  cat notice.txt | python scripts/ingest.py                 # from stdin
  python scripts/ingest.py --file article.txt --dry-run     # preview, write nothing

Then rebuild:
  node scripts/export_mongo.js && python scripts/load_mongo.py     # -> Atlas
  node scripts/export_graph.js                                     # -> data/graph
  # reload load.cypher in Neo4j, then: python scripts/embed_graph.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

DATA = Path(__file__).resolve().parent.parent / "data" / "industries.json"

# The exact industries a record may be classified into (must match the dataset).
INDUSTRIES = [
    "Healthcare and Social Assistance", "Finance and Insurance", "Manufacturing",
    "Retail Trade and Consumer Services", "Educational Services",
    "Public Administration (Government)", "Construction",
    "Transportation and Warehousing", "Agriculture, Forestry, Fishing and Food Production",
    "Energy and Utilities", "Accommodation, Food Services, Arts and Entertainment",
    "Information Technology", "Telecommunications",
    "Professional, Scientific, Technical Services, Real Estate and Wholesale Trade",
]

INCIDENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "incident_type": {"type": "string",
            "enum": ["ransomware", "data-extortion", "other-cyber", "not-a-specific-incident"],
            "description": "ransomware = encryption/ransom; data-extortion = threat actor stole data and extorted/threatened to leak (no encryption needed); other-cyber = adversarial breach without extortion; not-a-specific-incident = outage, accidental exposure, or not about one org"},
        "industry": {"type": "string", "enum": INDUSTRIES + ["UNKNOWN"]},
        "victim": {"type": "string"},
        "group": {"type": "string", "description": "ransomware group/gang, or 'not publicly disclosed'"},
        "date": {"type": "string", "description": "incident date if stated, else ''"},
        "country": {"type": "string"},
        "financial_impact": {"type": "string", "description": "reported cost/loss with the figure if given, else 'not publicly disclosed'"},
        "ransom_demanded_or_paid": {"type": "string"},
        "downtime_and_recovery": {"type": "string"},
        "data_impact": {"type": "string", "description": "records/people affected and data types"},
        "summary": {"type": "string", "description": "2-3 sentence factual summary"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["incident_type", "industry", "victim", "group", "date", "country",
                 "financial_impact", "ransom_demanded_or_paid", "downtime_and_recovery",
                 "data_impact", "summary", "sources"],
}

# Incident types we keep in the dataset (threat-actor-driven extortion).
ACCEPT_TYPES = {"ransomware", "data-extortion"}

SYSTEM = ("You extract structured cyber-extortion incident records for a ransomware-risk "
          "dataset. Use ONLY facts present in the text. For any figure not stated, write "
          "exactly 'not publicly disclosed' — never estimate. Classify the victim's industry "
          "into the provided list (closest match; UNKNOWN only if none fit). Set incident_type "
          "precisely: 'ransomware' or 'data-extortion' for threat-actor extortion (keep these), "
          "'other-cyber' for an adversarial breach with no extortion, 'not-a-specific-incident' "
          "for outages/accidental exposure or text not about one organisation.")


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _opt(args, name):
    """Value of --name=X or --name X, else None."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def get_text(args) -> tuple[str, str | None]:
    if url := _opt(args, "--url"):
        from urllib.request import Request, urlopen
        raw = urlopen(Request(url, headers={"User-Agent": "cna-ingest/1.0"}), timeout=60).read().decode("utf-8", "replace")
        return strip_html(raw)[:12000], url
    if fp := _opt(args, "--file"):
        return Path(fp).read_text(encoding="utf-8")[:12000], None
    if not sys.stdin.isatty():
        return sys.stdin.read()[:12000], None
    raise SystemExit("provide --file <path>, --url <url>, or pipe text on stdin")


def extract(text: str, source_url: str | None) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("pip install openai")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set")
    client = OpenAI()
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
        response_format={"type": "json_schema",
                         "json_schema": {"name": "incident", "schema": INCIDENT_SCHEMA, "strict": True}},
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": text}],
    )
    rec = json.loads(resp.choices[0].message.content)
    if source_url and source_url not in rec.get("sources", []):
        rec.setdefault("sources", []).insert(0, source_url)
    return rec


def to_incident(rec: dict) -> dict:
    """Map the extraction to the example_incidents shape used in industries.json."""
    return {
        "victim": rec["victim"], "group": rec.get("group") or None,
        "date": rec.get("date") or None, "country": rec.get("country") or None,
        "incident_type": rec.get("incident_type"), "ingest_source": "sec/news",
        "summary": rec.get("summary"),
        "financial_impact": rec.get("financial_impact"),
        "ransom_demanded_or_paid": rec.get("ransom_demanded_or_paid"),
        "downtime_and_recovery": rec.get("downtime_and_recovery"),
        "data_impact": rec.get("data_impact"),
        "sources": [s for s in rec.get("sources", []) if isinstance(s, str)],
    }


def ingest_record(rec: dict, dry: bool = False) -> str:
    """Validate + append one extracted record to industries.json. Returns a
    status: 'added' | 'dry' | 'skip:<reason>'. Reusable by batch fetchers."""
    if rec.get("incident_type") not in ACCEPT_TYPES:
        return f"skip:{rec.get('incident_type', 'unclassified')}"
    if rec.get("industry") in (None, "", "UNKNOWN"):
        return "skip:industry-unknown"
    if not (rec.get("victim") or "").strip():
        return "skip:no-victim"

    industries = json.loads(DATA.read_text(encoding="utf-8"))
    target = next((i for i in industries if i["industry"] == rec["industry"]), None)
    if target is None:
        return f"skip:no-such-industry:{rec['industry']}"

    existing = {(e.get("victim") or "").strip().lower() for e in target.get("example_incidents", [])}
    if rec["victim"].strip().lower() in existing:
        return "skip:duplicate"
    if dry:
        return "dry"

    target.setdefault("example_incidents", []).append(to_incident(rec))
    DATA.write_text(json.dumps(industries, indent=2, ensure_ascii=False), encoding="utf-8")
    return "added"


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    text, url = get_text(args)
    rec = extract(text, url)
    print(json.dumps(rec, indent=2, ensure_ascii=False))

    status = ingest_record(rec, dry)
    if status == "added":
        print(f"\nAdded '{rec['victim']}' to {rec['industry']}.")
        print("Rebuild to propagate:\n"
              "  node scripts/export_mongo.js && python scripts/load_mongo.py\n"
              "  node scripts/export_graph.js   # then reload load.cypher + python scripts/embed_graph.py")
    elif status == "dry":
        print(f"\n[dry-run] would add '{rec['victim']}' to {rec['industry']}.")
    else:
        print(f"\nSkipped ({status}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
