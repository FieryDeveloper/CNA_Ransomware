"""
Fetch ransomware victim records from the ransomware.live v2 API.

ransomware.live is the primary base-data source for this project: it is the only
free public ransomware leak-site tracker that tags victims with an industry
sector AND carries per-incident fields (ransom, press links, data size).

API notes (v2, free tier):
  - No authentication required.
  - Rate limited to 1 request/minute PER ENDPOINT. This script serializes
    requests and sleeps between them accordingly.
  - A free PRO key (500k calls/month) is available at https://my.ransomware.live
    If you have one, set RANSOMWARE_LIVE_API_KEY and it will be sent as a header,
    which lifts the 1 req/min limit.

Endpoints used:
  GET /v2/sectors                -> list of sector names
  GET /v2/sectorvictims/{sector} -> victims for one sector
  GET /v2/recentvictims          -> most recent victims across all sectors

IMPORTANT GOTCHA: the sector route is /v2/sectorvictims/{sector}. The plausible
-looking /v2/victims/sector/{sector} does NOT 404 — it returns HTTP 200 with the
API's HTML documentation page. A loose parser will silently produce an empty or
garbage dataset from it. assert_json() below guards against exactly this by
rejecting any response whose body starts with '<'.

Victim record fields:
  activity, attackdate, claim_url, country, data_size, description, discovered,
  domain, group, infostealer, press, ransom, screenshot, url, victim

Usage:
  python fetch_ransomware_live.py --all-sectors
  python fetch_ransomware_live.py --sector Healthcare
  python fetch_ransomware_live.py --recent
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_BASE = "https://api.ransomware.live/v2"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# Free tier allows 1 request per minute per endpoint. Sector queries all hit the
# same endpoint pattern, so we pace them a little over 60s apart.
FREE_TIER_DELAY_SECONDS = 62
API_KEY = os.environ.get("RANSOMWARE_LIVE_API_KEY")


def get(path: str, retries: int = 3):
    """GET a JSON endpoint, retrying with backoff on rate limits and transient errors."""
    url = f"{API_BASE}{path}"
    headers = {"User-Agent": "cna-ransomware-research/1.0", "Accept": "application/json"}
    if API_KEY:
        headers["X-API-KEY"] = API_KEY

    for attempt in range(1, retries + 1):
        try:
            with urlopen(Request(url, headers=headers), timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                # Guard: some wrong-but-plausible paths return 200 + an HTML docs
                # page rather than 404. Fail loudly instead of parsing garbage.
                if body.lstrip()[:1] == "<":
                    print(f"  ERROR: {url} returned HTML, not JSON "
                          f"(wrong endpoint?). Refusing to parse.", file=sys.stderr)
                    return None
                return json.loads(body)
        except HTTPError as e:
            if e.code == 429:
                # Rate limited. Honour Retry-After when the server sends one.
                wait = int(e.headers.get("Retry-After") or FREE_TIER_DELAY_SECONDS)
                print(f"  rate limited (429), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if 500 <= e.code < 600 and attempt < retries:
                wait = 5 * attempt
                print(f"  server error {e.code}, retry in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  HTTP {e.code} for {url}", file=sys.stderr)
            return None
        except (URLError, TimeoutError) as e:
            if attempt < retries:
                wait = 5 * attempt
                print(f"  network error ({e}), retry in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  giving up on {url}: {e}", file=sys.stderr)
            return None
    return None


def fetch_sectors() -> list[str]:
    data = get("/sectors")
    if not data:
        return []
    # Endpoint may return bare strings or objects keyed by name.
    if isinstance(data, list):
        return [s if isinstance(s, str) else (s.get("sector") or s.get("name")) for s in data]
    return list(data.keys())


def fetch_sector(sector: str) -> list[dict]:
    # NOTE: /sectorvictims/{sector} — NOT /victims/sector/{sector}, which
    # returns the HTML docs page with a 200. See module docstring.
    # safe="" is required: sector names like "Transportation/Logistics" contain
    # a slash that must be percent-encoded, or it splits the path and returns [].
    data = get(f"/sectorvictims/{quote(sector, safe='')}")
    return data if isinstance(data, list) else []


def fetch_recent() -> list[dict]:
    data = get("/recentvictims")
    return data if isinstance(data, list) else []


def fetch_year(year: int) -> list[dict]:
    """Victims posted in a given year, across all sectors.

    This is the reliable way to get complete coverage. /sectorvictims/{sector}
    cannot reach "Transportation/Logistics" at all — the slash in the sector
    name breaks the path and 404s under every encoding tried (raw, %2F, %252F,
    space, hyphen). Pulling by year and grouping on the `activity` field
    recovers that sector and cross-checks every other one.
    """
    data = get(f"/victims/{year}")
    return data if isinstance(data, list) else []


def write(name: str, payload) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch ransomware.live victim data")
    ap.add_argument("--all-sectors", action="store_true", help="fetch every sector (slow on free tier)")
    ap.add_argument("--sector", help="fetch a single sector, e.g. Healthcare")
    ap.add_argument("--recent", action="store_true", help="fetch recent victims across all sectors")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip sectors already on disk (resume an interrupted --all-sectors run)")
    ap.add_argument("--years", metavar="FROM-TO",
                    help="fetch every victim by year, e.g. 2015-2026 (recovers Transportation/Logistics)")
    args = ap.parse_args()

    if args.years:
        lo, _, hi = args.years.partition("-")
        lo, hi = int(lo), int(hi or lo)
        everything: list[dict] = []
        for n, year in enumerate(range(lo, hi + 1)):
            path = OUT_DIR / f"year_{year}.json"
            if args.skip_existing and path.exists() and path.stat().st_size > 2:
                recs = json.loads(path.read_text(encoding="utf-8-sig"))
                print(f"{year}: {len(recs)} (cached)")
            else:
                if n and not API_KEY:
                    time.sleep(FREE_TIER_DELAY_SECONDS)
                recs = fetch_year(year)
                write(f"year_{year}.json", recs)
                print(f"{year}: {len(recs)}", flush=True)
            everything.extend(recs)

        by_sector: dict[str, list[dict]] = {}
        for v in everything:
            by_sector.setdefault(v.get("activity") or "(unclassified)", []).append(v)
        print(f"\ntotal {len(everything)} victims across {len(by_sector)} sectors")
        for sector, recs in sorted(by_sector.items(), key=lambda kv: -len(kv[1])):
            slug = sector.lower().replace("/", "_").replace(" ", "_")
            write(f"byyear_sector_{slug}.json", recs)
            print(f"  {sector:38s} {len(recs)}")
        return 0

    if not (args.all_sectors or args.sector or args.recent):
        ap.print_help()
        return 1

    if args.recent:
        victims = fetch_recent()
        print(f"recent victims: {len(victims)} -> {write('recent_victims.json', victims)}")

    if args.sector:
        victims = fetch_sector(args.sector)
        slug = args.sector.lower().replace("/", "_").replace(" ", "_")
        print(f"{args.sector}: {len(victims)} -> {write(f'sector_{slug}.json', victims)}")

    if args.all_sectors:
        sectors = fetch_sectors()
        if not sectors:
            print("could not retrieve sector list", file=sys.stderr)
            return 1
        print(f"found {len(sectors)} sectors")
        combined: dict[str, list[dict]] = {}

        for i, sector in enumerate(sectors, 1):
            if not sector:
                continue
            slug_existing = sector.lower().replace("/", "_").replace(" ", "_")
            existing_path = OUT_DIR / f"sector_{slug_existing}.json"
            if args.skip_existing and existing_path.exists() and existing_path.stat().st_size > 2:
                try:
                    combined[sector] = json.loads(existing_path.read_text(encoding="utf-8-sig"))
                    print(f"[{i}/{len(sectors)}] {sector} — already on disk ({len(combined[sector])}), skipping")
                    continue
                except (json.JSONDecodeError, OSError):
                    print(f"[{i}/{len(sectors)}] {sector} — existing file unreadable, refetching")

            print(f"[{i}/{len(sectors)}] {sector}...", flush=True)
            victims = fetch_sector(sector)
            combined[sector] = victims
            slug = sector.lower().replace("/", "_").replace(" ", "_")
            write(f"sector_{slug}.json", victims)
            print(f"  {len(victims)} victims")

            # Pace for the free tier unless we hold a PRO key.
            if not API_KEY and i < len(sectors):
                time.sleep(FREE_TIER_DELAY_SECONDS)

        total = sum(len(v) for v in combined.values())
        print(f"total {total} victims across {len(combined)} sectors -> {write('all_sectors.json', combined)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
