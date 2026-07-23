"""
Fetch ransomware leak-site posts from RansomLook and ransomwatch.

These are CORROBORATION sources, not the base data source. Important limitation
discovered while building this dataset:

  - RansomLook's public API is GROUP-centric. There is no victim-by-sector
    endpoint, and posts carry only group_name / post_title / discovered.
  - ransomwatch's posts.json likewise carries only post_title, group_name and
    discovered.

Neither tags victims with an industry sector, which is why ransomware.live is
used as the sector spine (see fetch_ransomware_live.py) and these two are used
to cross-check that a victim really was posted and to widen group coverage.

Endpoints:
  RansomLook   GET https://www.ransomlook.io/api/recent
               GET https://www.ransomlook.io/api/posts/{days}
               GET https://www.ransomlook.io/api/group/{name}
               GET https://www.ransomlook.io/api/search/{query}
  ransomwatch  GET https://ransomwhat.telemetry.ltd/posts.json
               GET https://ransomwhat.telemetry.ltd/groups.json

Usage:
  python fetch_ransomlook.py --ransomwatch
  python fetch_ransomlook.py --ransomlook-recent
  python fetch_ransomlook.py --search "university"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

RANSOMLOOK_BASE = "https://www.ransomlook.io/api"
RANSOMWATCH_POSTS = "https://ransomwhat.telemetry.ltd/posts.json"
RANSOMWATCH_GROUPS = "https://ransomwhat.telemetry.ltd/groups.json"

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def get_json(url: str, retries: int = 3):
    headers = {"User-Agent": "cna-ransomware-research/1.0", "Accept": "application/json"}
    for attempt in range(1, retries + 1):
        try:
            with urlopen(Request(url, headers=headers), timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except HTTPError as e:
            if e.code == 429 or (500 <= e.code < 600 and attempt < retries):
                wait = 5 * attempt
                print(f"  HTTP {e.code}, retry in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  HTTP {e.code} for {url}", file=sys.stderr)
            return None
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < retries:
                wait = 5 * attempt
                print(f"  error ({e}), retry in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  giving up on {url}: {e}", file=sys.stderr)
            return None
    return None


def write(name: str, payload) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def match_victims(posts: list[dict], names: list[str]) -> list[dict]:
    """Cross-check: return posts whose title mentions any of the given victim names.

    Used to confirm a ransomware.live victim also appears on another tracker.
    Matching is deliberately loose (case-insensitive substring) because leak-site
    post titles are inconsistently formatted.
    """
    out = []
    lowered = [(n, n.lower()) for n in names if n]
    for p in posts:
        title = (p.get("post_title") or "").lower()
        if not title:
            continue
        for original, needle in lowered:
            if needle in title:
                out.append({**p, "matched_victim": original})
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch RansomLook / ransomwatch corroboration data")
    ap.add_argument("--ransomwatch", action="store_true", help="fetch ransomwatch posts.json and groups.json")
    ap.add_argument("--ransomlook-recent", action="store_true", help="fetch RansomLook recent posts")
    ap.add_argument("--search", help="search RansomLook posts for a keyword")
    ap.add_argument("--match-file", help="JSON file of victim names to cross-check against ransomwatch posts")
    args = ap.parse_args()

    if not any([args.ransomwatch, args.ransomlook_recent, args.search, args.match_file]):
        ap.print_help()
        return 1

    posts = None

    if args.ransomwatch or args.match_file:
        print("fetching ransomwatch posts.json (large, be patient)...")
        posts = get_json(RANSOMWATCH_POSTS) or []
        print(f"  {len(posts)} posts -> {write('ransomwatch_posts.json', posts)}")

    if args.ransomwatch:
        groups = get_json(RANSOMWATCH_GROUPS) or []
        print(f"  {len(groups)} groups -> {write('ransomwatch_groups.json', groups)}")

    if args.ransomlook_recent:
        recent = get_json(f"{RANSOMLOOK_BASE}/recent") or []
        print(f"RansomLook recent: {len(recent)} -> {write('ransomlook_recent.json', recent)}")

    if args.search:
        results = get_json(f"{RANSOMLOOK_BASE}/search/{quote(args.search)}") or []
        slug = args.search.lower().replace(" ", "_")
        print(f"RansomLook search '{args.search}': {len(results)} -> {write(f'ransomlook_search_{slug}.json', results)}")

    if args.match_file:
        names = json.loads(Path(args.match_file).read_text(encoding="utf-8"))
        if isinstance(names, dict):
            names = list(names.keys())
        matches = match_victims(posts or [], names)
        print(f"cross-checked {len(names)} victims: {len(matches)} matched -> {write('ransomwatch_matches.json', matches)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
