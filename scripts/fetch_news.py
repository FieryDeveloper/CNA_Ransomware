"""
fetch_news.py — harvest ransomware incidents from security news, into the schema.

The only scrapeable route to per-incident DOWNTIME and rich attack details is
news reporting. This walks a site's ransomware tag pages, pulls each article, and
runs it through the same LLM classifier as ingest.py (which extracts victim,
group, ransom demanded/paid, downtime/recovery, data impact, summary, sources).

Sources:
  - BleepingComputer (bleepingcomputer.com/tag/ransomware) — works over HTTP.
  - The Record (therecord.media) — blocks non-browser access from some networks
    (curl fails at the connection level); left as a documented extension that
    needs a headless-browser fetch (see fetch_comparitech.py for the pattern).

Yield is modest and overlaps big incidents already in the set — but it is the
only source that carries downtime + narrative. Run it periodically to top up.

Setup: pip install -r requirements.txt ; set OPENAI_API_KEY (in .env)

Usage:
  python scripts/fetch_news.py --pages 3 --limit 40 --dry-run
  python scripts/fetch_news.py --pages 10 --limit 150        # then rebuild
"""

from __future__ import annotations

import os
import re
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import extract, ingest_record, strip_html

# Resume cache: URLs already classified, so re-runs continue to fresh articles
# instead of re-fetching + re-LLM'ing the same ones. Gitignored.
from pathlib import Path
SEEN_FILE = Path(__file__).resolve().parent.parent / "data" / ".news_seen.txt"


def load_seen() -> set:
    return set(SEEN_FILE.read_text(encoding="utf-8").split()) if SEEN_FILE.exists() else set()


def mark_seen(url: str):
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}

SOURCES = {
    "bleepingcomputer": {
        "tag": "https://www.bleepingcomputer.com/tag/ransomware/",
        "page": "https://www.bleepingcomputer.com/tag/ransomware/page/{n}/",
        "article_re": r"https://www\.bleepingcomputer\.com/news/[a-z-]+/[a-z0-9-]+/",
        "body_re": r'class="[^"]*articleBody[^"]*"[^>]*>(.*?)(?:<div[^>]*class="[^"]*(?:cz-related|tags|comment))',
    },
}


def get(url: str, retries: int = 3) -> str:
    import gzip
    for attempt in range(retries):
        try:
            r = urlopen(Request(url, headers=HEADERS), timeout=45)
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(str(e))
    return ""


def article_body(html: str, body_re: str) -> str:
    m = re.search(body_re, html, re.S)
    raw = m.group(1) if m else html
    return strip_html(raw)[:10000]


def title_of(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    return re.sub(r"\s+", " ", (m.group(1) if m else "")).strip()[:90]


def collect_links(src: dict, pages: int) -> list[str]:
    seen, links = set(), []
    for n in range(1, pages + 1):
        url = src["tag"] if n == 1 else src["page"].format(n=n)
        try:
            html = get(url)
        except Exception as e:
            print(f"  (page {n} failed: {e})")
            break
        found = [u for u in re.findall(src["article_re"], html)]
        new = [u for u in found if u not in seen]
        for u in new:
            seen.add(u); links.append(u)
        print(f"  page {n}: {len(new)} new article links")
        if not new:
            break
        time.sleep(0.5)
    return links


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    pages = int(next((a.split("=")[1] for a in args if a.startswith("--pages=")),
                     _val(args, "--pages", "3")))
    limit = int(next((a.split("=")[1] for a in args if a.startswith("--limit=")),
                     _val(args, "--limit", "40")))
    which = _val(args, "--source", "bleepingcomputer")
    src = SOURCES.get(which)
    if not src:
        raise SystemExit(f"unknown source '{which}'. options: {', '.join(SOURCES)}")

    print(f"[{which}] collecting article links across {pages} page(s)...")
    links = collect_links(src, pages)
    seen_urls = load_seen()
    fresh = [u for u in links if u not in seen_urls]
    print(f"found {len(links)} articles ({len(links) - len(fresh)} already done); "
          f"classifying up to {limit} fresh\n")

    counts, processed, seen = {}, 0, set()
    for url in fresh:
        if processed >= limit:
            break
        processed += 1
        mark_seen(url)   # record even skips, so we don't re-fetch next run
        try:
            html = get(url)
            text = title_of(html) + ". " + article_body(html, src["body_re"])
            rec = extract(text, url)
            vkey = re.sub(r"[^a-z0-9]+", " ", (rec.get("victim") or "").lower()).strip()
            if vkey and vkey in seen:
                status = "skip:duplicate-in-batch"
            else:
                status = ingest_record(rec, dry)
                if status in ("added", "dry"):
                    seen.add(vkey)
        except Exception as e:
            status = f"error:{str(e)[:50]}"
        key = status.split(":")[0]
        counts[key] = counts.get(key, 0) + 1
        flag = {"added": "+", "dry": "~", "error": "!"}.get(key, "-")
        extra = (f" -> {rec['victim']} / {rec['industry']}"
                 + (f" [{rec['ransom_demanded_or_paid'][:40]}]"
                    if rec.get("ransom_demanded_or_paid") and "not " not in rec["ransom_demanded_or_paid"].lower() else "")
                 ) if status in ("added", "dry") else ""
        print(f"  {flag} [{status}]{extra or ' ' + url.split('/')[-2][:50]}")
        time.sleep(0.3)

    print(f"\n{'[dry-run] ' if dry else ''}processed {processed}: " +
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if counts.get("added"):
        print("\nRebuild: node scripts/export_mongo.js && python scripts/load_mongo.py ; "
              "node scripts/export_graph.js ; reload cypher ; python scripts/embed_graph.py")
    return 0


def _val(args, name, default):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


if __name__ == "__main__":
    raise SystemExit(main())
