"""
load_mongo.py — load the exported collections into MongoDB Atlas.

Reads the JSON that export_mongo.js produced in data/mongo/ and upserts it into
Atlas, then creates the indexes the app and analytics rely on. Idempotent: every
document is keyed by _id and replaced in place, so re-running after a re-scrape
updates rather than duplicates.

Setup (one time):
  1. Create a free cluster at https://cloud.mongodb.com (M0 tier is fine).
  2. Database Access  -> add a user with a password.
  3. Network Access   -> allow your IP (or 0.0.0.0/0 for a demo).
  4. Connect -> Drivers -> copy the connection string, and set:
       export MONGODB_URI='mongodb+srv://USER:PASS@cluster0.xxxx.mongodb.net/'
       export MONGODB_DB='cna_ransomware'      # optional, this is the default
     (or put MONGODB_URI in .env, which this script now reads automatically)
  5. pip install pymongo
  6. node scripts/export_mongo.js      # refresh data/mongo/
     python scripts/load_mongo.py

Flags:
  --dry-run   validate the JSON and print what would load; no connection, no
              pymongo needed. Use this to sanity-check before touching Atlas.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MONGO_DIR = Path(__file__).resolve().parent.parent / "data" / "mongo"


def _load_env():
    """Read .env the way rag_core.py does, so MONGODB_URI does not have to be
    exported by hand. Stdlib only: this script must run on a bare install, and
    python-dotenv is optional elsewhere in the project. Real environment
    variables always win over .env."""
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
DB_NAME = os.environ.get("MONGODB_DB", "cna_ransomware")

# collection -> index specs. Each spec is (keys, options).
INDEXES = {
    "victims": [
        ([("sector_key", 1)], {}),
        ([("group", 1)], {}),
        ([("year", 1)], {}),
        ([("country", 1)], {}),
        ([("sector_key", 1), ("year", 1)], {}),
    ],
    "incidents": [
        ([("industry_id", 1)], {}),
        ([("financial.usd", -1)], {}),
        ([("ransom.usd", -1)], {}),
        ([("group", 1)], {}),
    ],
    "industries": [([("ransomware_live_sector", 1)], {})],
    "taxonomy": [([("type", 1)], {}), ([("family", 1)], {}), ([("reach", -1)], {})],
    "groups": [([("ransom_paid_usd", -1)], {})],
    "comparitech": [([("ransom_amount_usd", -1)], {}), ([("strain", 1)], {}), ([("ransom_paid", 1)], {})],
    # Frequency model (scripts/fetch_exposure.py -> estimate_underreporting.py -> build_frequency.py)
    "frequency": [
        ([("kind", 1)], {}),
        ([("industry_id", 1), ("size_band", 1)], {}),
        ([("rate.central_per_10k", -1)], {}),
        ([("exposure_year", 1)], {}),
    ],
    "frequency_exposure": [([("kind", 1)], {}), ([("industry_id", 1), ("size_band", 1)], {})],
    "frequency_calibration": [],
    # HHS OCR mandatory healthcare breach list (scripts/fetch_hhs_ocr.py)
    "hhs_ocr": [
        ([("individuals_affected", -1)], {}),
        ([("breach_submission_date_iso", -1)], {}),
        ([("state", 1)], {}),
        ([("ransomware_indicated", 1)], {}),
        ([("covered_entity_type", 1)], {}),
    ],
}

# Larger collections load in batches to keep memory and request sizes sane.
BATCH = 2000


def load_file(name: str) -> list[dict]:
    path = MONGO_DIR / f"{name}.json"
    if not path.exists():
        hint = ("python scripts/fetch_hhs_ocr.py" if name == "hhs_ocr" else
                "python scripts/fetch_exposure.py / estimate_underreporting.py / build_frequency.py"
                if name.startswith("frequency") else "node scripts/export_mongo.js")
        raise SystemExit(f"missing {path} — run `{hint}` first")
    with open(path, encoding="utf-8") as fh:
        docs = json.load(fh)
    return docs if isinstance(docs, list) else [docs]


COLLECTIONS = ["industries", "incidents", "victims", "taxonomy", "insights", "synthesis",
               "groups", "comparitech",
               # Frequency model. Produced by the Python pipeline, not export_mongo.js:
               #   python scripts/fetch_exposure.py
               #   python scripts/estimate_underreporting.py
               #   python scripts/build_frequency.py
               "frequency_exposure", "frequency_calibration", "frequency",
               # Healthcare's mandatory breach list (python scripts/fetch_hhs_ocr.py)
               "hhs_ocr"]


def dry_run() -> int:
    print(f"DRY RUN - validating data/mongo/ (db would be '{DB_NAME}')\n")
    ok = True
    for name in COLLECTIONS:
        try:
            docs = load_file(name)
        except SystemExit as e:
            print(f"  {name:22} MISSING - {e}")
            ok = False
            continue
        missing_id = sum(1 for d in docs if not d.get("_id"))
        note = f" ({missing_id} missing _id!)" if missing_id else ""
        idx = len(INDEXES.get(name, []))
        print(f"  {name:22} {len(docs):>6} docs, {idx} index(es){note}")
        if missing_id:
            ok = False
    print("\nOK - nothing was written." if ok else "\nPROBLEMS found (see above).")
    return 0 if ok else 1


def real_run() -> int:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise SystemExit("set MONGODB_URI in .env or the environment (see the setup notes at "
                         "the top of this file), or use --dry-run")
    try:
        from pymongo import MongoClient, ReplaceOne
    except ImportError:
        raise SystemExit("pymongo not installed - run: pip install pymongo")

    client = MongoClient(uri)
    client.admin.command("ping")  # fail fast on bad credentials / network
    db = client[DB_NAME]
    print(f"connected -> {DB_NAME}\n")

    for name in COLLECTIONS:
        path = MONGO_DIR / f"{name}.json"
        if not path.exists():
            print(f"  {name:22} (no file — skipped; optional)")
            continue
        docs = load_file(name)
        coll = db[name]
        total = 0
        for i in range(0, len(docs), BATCH):
            chunk = docs[i:i + BATCH]
            ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in chunk]
            res = coll.bulk_write(ops, ordered=False)
            total += (res.upserted_count or 0) + (res.modified_count or 0) + (res.matched_count or 0)
        for keys, opts in INDEXES.get(name, []):
            coll.create_index(keys, **opts)
        print(f"  {name:22} {len(docs):>6} docs upserted, {len(INDEXES.get(name, []))} index(es)")

    print("\ndone.")
    client.close()
    return 0


def main() -> int:
    if "--dry-run" in sys.argv:
        return dry_run()
    return real_run()


if __name__ == "__main__":
    raise SystemExit(main())
