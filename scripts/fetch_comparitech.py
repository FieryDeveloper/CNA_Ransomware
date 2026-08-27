"""
fetch_comparitech.py — extract Comparitech's ransomware map (per-incident data).

Comparitech's ransomware attack map is a Tableau Public workbook whose marks carry
exactly the fields we're short on: company, ransom amount, ransom PAID (yes/no),
ransomware strain (attacker), industry, records affected. Modern Tableau Public
renders client-side, so static scraping fails — we drive headless Chrome, let the
viz bootstrap, and capture the `bootstrapSession` response (the data payload),
then parse it with tableauscraper.

Yield (US map): ~5,034 incidents; 427 with a ransom amount, 171 confirmed paid,
3,317 with an attacker strain — far more ransom data than any other public source.

Requires: pip install pychrome tableauscraper ; Google Chrome installed.
Note: no per-incident DATE in the map marks (the map filters by year but doesn't
encode it per point), so `date` is left null.

Usage:
  python scripts/fetch_comparitech.py            # -> data/mongo/comparitech.json
  python scripts/fetch_comparitech.py --dry-run
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

OUT = Path(__file__).resolve().parent.parent / "data" / "mongo" / "comparitech.json"
DEBUG_PORT = 9222

# Tableau Public views to pull. Add the worldwide workbook here once its view
# name is confirmed; the US map is the bulk of the data.
VIEWS = [
    ("US", "https://public.tableau.com/views/USRansomwareAttacksMap-3/Dashboard1?:embed=y&:showVizHome=no"),
]

CHROME = next((p for p in [
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "google-chrome", "chromium", "chrome",
] if os.path.exists(p) or "/" not in p), "chrome")


def _debug_up() -> bool:
    try:
        urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=3).read()
        return True
    except Exception:
        return False


def ensure_chrome():
    if _debug_up():
        return None
    prof = Path(os.environ.get("TEMP", "/tmp")) / "cna_chromedbg"
    p = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu",
                          f"--remote-debugging-port={DEBUG_PORT}",
                          f"--user-data-dir={prof}", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if _debug_up():
            return p
        time.sleep(0.5)
    raise SystemExit("could not start Chrome with remote debugging")


def capture(url: str) -> str:
    """Load the viz and return the raw bootstrapSession response body."""
    import pychrome
    browser = pychrome.Browser(url=f"http://127.0.0.1:{DEBUG_PORT}")
    tab = browser.new_tab()
    want, bodies = set(), []

    def on_resp(**kw):
        if "bootstrapSession" in kw.get("response", {}).get("url", ""):
            want.add(kw.get("requestId"))

    def on_done(**kw):
        rid = kw.get("requestId")
        if rid in want:
            try:
                bodies.append(tab.Network.getResponseBody(requestId=rid).get("body", ""))
            except Exception:
                pass

    tab.Network.responseReceived = on_resp
    tab.Network.loadingFinished = on_done
    tab.start(); tab.Network.enable(); tab.Page.enable()
    tab.Page.navigate(url=url)
    for _ in range(30):
        time.sleep(1)
        if bodies:
            time.sleep(2); break
    tab.stop(); browser.close_tab(tab)
    return max(bodies, key=len) if bodies else ""


def parse_chunks(s: str) -> list:
    out, i = [], 0
    while i < len(s):
        j = s.find(";", i)
        if j < 0:
            break
        try:
            n = int(s[i:j])
        except ValueError:
            break
        out.append(json.loads(s[j + 1:j + 1 + n]))
        i = j + 1 + n
    return out


NULLS = {"%null%", "Unknown", "", "nan", "None", "%all%", "%many-values%"}


def clean(v):
    v = str(v).strip()
    return None if v in NULLS else v


def num(v):
    v = clean(v)
    if v is None:
        return None
    d = re.sub(r"[^0-9.]", "", v)
    try:
        return float(d) if d else None
    except ValueError:
        return None


def extract(region: str, raw: str) -> list[dict]:
    from tableauscraper import TableauScraper, dashboard
    info, data = parse_chunks(raw)
    wb = dashboard.getWorksheets(TableauScraper(), data, info)
    # the incident worksheet carries "Company Affected"; several sheets do
    # (state insets like Alaska/Hawaii), so take the LARGEST — the main map.
    cands = [w for w in wb.worksheets if any("Company Affected" in c for c in w.data.columns)]
    if not cands:
        return []
    ws = max(cands, key=lambda w: len(w.data))
    df = ws.data
    col = lambda name: (df[f"ATTR({name})-alias"] if f"ATTR({name})-alias" in df
                        else df[f"{name}-alias"] if f"{name}-alias" in df else [None] * len(df))
    recs = []
    for i in range(len(df)):
        company = clean(col("Company Affected").iloc[i])
        if not company:
            continue
        recs.append({
            "_id": f"comparitech:{region}:{re.sub(r'[^a-z0-9]+', '-', company.lower())[:80]}",
            "company": company,
            "industry": clean(col("Industry").iloc[i]),
            "records_affected": num(col("# Records Affected").iloc[i]),
            "ransom_amount_usd": num(col("Ransom Amount").iloc[i]),
            "ransom_paid": clean(col("Ransom Paid").iloc[i]),   # Yes / No / None
            "strain": clean(col("Ransomware Strain").iloc[i]),   # attacker
            "region": region,
            "source": "comparitech.com/ransomware-attack-map",
        })
    return recs


def main() -> int:
    dry = "--dry-run" in sys.argv
    try:
        import pychrome  # noqa
    except ImportError:
        raise SystemExit("pip install pychrome tableauscraper")

    proc = ensure_chrome()
    try:
        all_recs, seen = [], set()
        for region, url in VIEWS:
            print(f"capturing {region} map ...")
            raw = capture(url)
            if not raw:
                print(f"  no data captured for {region}")
                continue
            recs = extract(region, raw)
            for r in recs:
                if r["_id"] in seen:
                    continue
                seen.add(r["_id"]); all_recs.append(r)
            print(f"  {region}: {len(recs)} incidents")
    finally:
        if proc:
            proc.terminate()

    with_amt = sum(1 for r in all_recs if r["ransom_amount_usd"])
    paid = sum(1 for r in all_recs if r["ransom_paid"] == "Yes")
    strain = sum(1 for r in all_recs if r["strain"])
    print(f"\ntotal: {len(all_recs)} incidents | ransom amount: {with_amt} | "
          f"confirmed paid: {paid} | with attacker: {strain}")
    if dry:
        print("\n[dry-run] not written. sample:")
        for r in [x for x in all_recs if x["ransom_amount_usd"]][:5]:
            print(f"  {r['company']} | {r['strain']} | ${r['ransom_amount_usd']:,.0f} | paid={r['ransom_paid']}")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_recs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {len(all_recs)} -> {OUT}")
    print("add 'comparitech' to load_mongo COLLECTIONS, then: python scripts/load_mongo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
