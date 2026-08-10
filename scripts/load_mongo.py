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
}

# Larger collections load in batches to keep memory and request sizes sane.
BATCH = 2000


def load_file(name: str) -> list[dict]:
    path = MONGO_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"missing {path} — run `node scripts/export_mongo.js` first")
    with open(path, encoding="utf-8") as fh:
        docs = json.load(fh)
    return docs if isinstance(docs, list) else [docs]


COLLECTIONS = ["industries", "incidents", "victims", "taxonomy", "insights", "synthesis"]


def dry_run() -> int:
    print(f"DRY RUN - validating data/mongo/ (db would be '{DB_NAME}')\n")
    ok = True
    for name in COLLECTIONS:
        try:
            docs = load_file(name)
        except SystemExit as e:
            print(f"  {name:12} MISSING - {e}")
            ok = False
            continue
        missing_id = sum(1 for d in docs if not d.get("_id"))
        note = f" ({missing_id} missing _id!)" if missing_id else ""
        idx = len(INDEXES.get(name, []))
        print(f"  {name:12} {len(docs):>6} docs, {idx} index(es){note}")
        if missing_id:
            ok = False
    print("\nOK - nothing was written." if ok else "\nPROBLEMS found (see above).")
    return 0 if ok else 1


def real_run() -> int:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise SystemExit("set MONGODB_URI (see the setup notes at the top of this file), "
                         "or use --dry-run")
    try:
        from pymongo import MongoClient, ReplaceOne
    except ImportError:
        raise SystemExit("pymongo not installed - run: pip install pymongo")

    client = MongoClient(uri)
    client.admin.command("ping")  # fail fast on bad credentials / network
    db = client[DB_NAME]
    print(f"connected -> {DB_NAME}\n")

    for name in COLLECTIONS:
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
        print(f"  {name:12} {len(docs):>6} docs upserted, {len(INDEXES.get(name, []))} index(es)")

    print("\ndone.")
    client.close()
    return 0


def main() -> int:
    if "--dry-run" in sys.argv:
        return dry_run()
    return real_run()


if __name__ == "__main__":
    raise SystemExit(main())
