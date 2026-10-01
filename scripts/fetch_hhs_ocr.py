"""
fetch_hhs_ocr.py — the HHS OCR breach portal: healthcare's MANDATORY breach list.

Why this one matters more than its size suggests: every other victim list in this
project is voluntary or adversarial (leak sites publish what they choose; news
covers what is newsworthy). HIPAA-covered entities MUST report breaches affecting
500+ individuals to HHS OCR. Within that stratum the list is close to a census,
which makes it the best available independent list for calibrating how much the
leak-site data undercounts.

It is also the most hostile endpoint in the project. There is no API and no CSV
export. The portal is a JSF/PrimeFaces app that:
  - 302s breach_report.jsf back to the front page, so you cannot deep-link the table;
  - reaches the table only through a Mojarra command link whose id (j_idt39) is
    auto-generated and WILL drift between deployments, so we discover it by anchor
    text instead of hardcoding it;
  - splits the data across a TabView: "Under Investigation" (last 24 months) and
    "Archive" (everything resolved). Both are needed; the default view is only the
    first and is roughly a tenth of the total;
  - pages through a PrimeFaces DataTable over AJAX, capped at 100 rows per page,
    returning partial-response XML rather than HTML;
  - rotates javax.faces.ViewState on every single request, including inside the
    AJAX responses, so the token must be re-read from each response or the next
    request dies with a ViewExpiredException.

Scope caveat that must travel with the numbers: HHS lists ALL breach types, not
just ransomware, and only those affecting 500+ individuals. Use --ransomware-only
for the extortion subset, and never read this as a census of small-practice incidents.

Writes data/mongo/hhs_ocr.json

Usage:
  python scripts/fetch_hhs_ocr.py --dry-run
  python scripts/fetch_hhs_ocr.py                      # both tabs
  python scripts/fetch_hhs_ocr.py --tab archive
"""

from __future__ import annotations

import gzip
import html as htmllib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "mongo" / "hhs_ocr.json"
NOW = datetime.now(timezone.utc).isoformat()

ENTRY = "https://ocrportal.hhs.gov/ocr/breach/breach_report.jsf"
NAV_LABEL = "View HIPAA Breach Reports"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PAGE_ROWS = 100            # the portal's own maximum
# Tab panels, in render order. We switch tabs by sending the panel's CLIENT ID as
# _newTab — sending the index instead gets you redirected to error_breach.jsf.
TAB_ORDER = ["investigation", "archive", "help"]
SCRAPE_TABS = ["investigation", "archive"]

# Columns, in the order the portal renders them.
COLS = ["covered_entity", "state", "covered_entity_type", "individuals_affected",
        "breach_submission_date", "breach_type", "breach_location",
        "business_associate_present", "web_description"]

# Ransomware detection on the HHS web description. Deliberately does NOT include a
# bare "encrypt": HIPAA descriptions use encryption as MITIGATION language ("an
# employee sent an unencrypted email", "the laptop was encrypted"), which inflated
# the count by ~36% (1,858 -> 1,340) and poisoned a calibration input. Attempting to
# rescue attack-only encryption phrasing added 22 records at roughly 50% precision,
# so it is dropped: "ransom" plus named strains is precise and sufficient.
# Strain names are WORD-BOUNDED. Unbounded, "conti" matched 90 descriptions via
# "continued"/"continuing" and "hive" matched 12 via "archive" — 102 spurious
# ransomware flags, every one of them removed by . "ransom" and "extort" need no
# boundary: they only appear as the real thing or as "ransomware".
_STRAINS = (r"lockbit|blackcat|alphv|conti|hive|clop|cl0p|akira|royal|black ?basta|maze|"
            r"ryuk|karakurt|qilin|rhysida|medusa|netwalker|revil|sodinokibi|play|"
            r"bianlian|cactus|inc ransom|everest|8base|snatch|trigona|nokoyawa")
RANSOM_RE = re.compile(r"ransom|extort|(?:" + _STRAINS + r")", re.I)


class Portal:
    """A JSF session. Holds the cookie jar and the rotating ViewState."""

    def __init__(self):
        jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.op.addheaders = [("User-Agent", UA), ("Accept-Encoding", "gzip")]
        self.url = ENTRY
        self.vs = None

    def _send(self, url, data=None, ajax=False, retries=3):
        for attempt in range(retries):
            try:
                body = urllib.parse.urlencode(data).encode() if data else None
                req = urllib.request.Request(url, data=body)
                if data:
                    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
                if ajax:
                    req.add_header("Faces-Request", "partial/ajax")
                    req.add_header("X-Requested-With", "XMLHttpRequest")
                r = self.op.open(req, timeout=120)
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return r.geturl(), raw.decode("utf-8", "replace")
            except Exception as e:
                if attempt == retries - 1:
                    raise
                print(f"    (retry {attempt+1}: {str(e)[:70]})")
                time.sleep(2 * (attempt + 1))

    def _absorb(self, text):
        """ViewState rotates on every response, including inside AJAX XML."""
        m = (re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]*)"', text)
             or re.search(r'<update id="[^"]*ViewState[^"]*"><!\[CDATA\[(.*?)\]\]></update>', text, re.S))
        if m:
            self.vs = htmllib.unescape(m.group(1))
        return text

    def get(self, url):
        self.url, text = self._send(url)
        return self._absorb(text)

    def post(self, data, ajax=False):
        data = dict(data)
        data.setdefault("javax.faces.ViewState", self.vs)
        url, text = self._send(self.url, data, ajax=ajax)
        if not ajax:
            self.url = url
        if "ViewExpiredException" in text:
            raise RuntimeError("JSF ViewState expired — the session was dropped mid-scrape")
        return self._absorb(text)


def discover_nav(html: str, label: str):
    """The command link id is auto-generated; find it by its anchor text."""
    for m in re.finditer(r"mojarra\.jsfcljs\(document\.getElementById\('([^']+)'\),"
                         r"\{'([^']+)':'[^']+'\}[^>]*>([^<]*)", html):
        if label.lower() in m.group(3).strip().lower():
            return m.group(1), m.group(2)
    raise RuntimeError(f"could not find the '{label}' command link — the portal markup changed")


def widget_ids(html: str):
    """Pull the DataTable + TabView client ids and the row count out of the
    PrimeFaces widget config, rather than assuming generated ids."""
    dt = re.search(r'PrimeFaces\.cw\("DataTable","[^"]*",\{id:"([^"]+)"'
                   r'.*?rowCount:(\d+)', html, re.S)
    tv = re.search(r'PrimeFaces\.cw\("TabView","[^"]*",\{id:"([^"]+)"', html)
    if not dt:
        raise RuntimeError("no DataTable widget on the page — portal markup changed")
    return dt.group(1), int(dt.group(2)), (tv.group(1) if tv else None)


def strip(s: str) -> str:
    s = re.sub(r"<script.*?</script>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]*>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def parse_rows(fragment: str) -> list[dict]:
    """Each data row carries data-ri (its index); row-expansion <tr>s do not, which
    is what keeps expanded description panels out of the row list.

    Columns are taken POSITIONALLY after dropping the leading row-toggler cell.
    Do not filter empty cells to realign: the toggler cell and the web-description
    cell are both empty in the collapsed view, so dropping empties happens to give
    the right answer today and would silently shift every column the moment a
    middle cell (e.g. State) came back blank."""
    out = []
    for m in re.finditer(r'<tr[^>]*data-ri="(\d+)"[^>]*>(.*?)</tr>', fragment, re.S):
        raw = re.findall(r"<td[^>]*>(.*?)</td>", m.group(2), re.S)
        if raw and "ui-row-toggler" in raw[0]:
            raw = raw[1:]
        cells = [strip(c) for c in raw[:len(COLS)]]
        if len(cells) < 6:
            continue
        rec = dict(zip(COLS, cells))
        rec["_row_index"] = int(m.group(1))
        rec["_row_key"] = (re.search(r'data-rk="([^"]+)"', m.group(0)) or [None, None])[1] \
            if 'data-rk="' in m.group(0) else None
        out.append(rec)
    return out


def tab_panels(html: str) -> list[str]:
    """The TabView panel client ids, in render order."""
    return re.findall(r'<div[^>]*id="(ocrForm:[^"]*)"[^>]*class="[^"]*ui-tabs-panel', html)


def fetch_description(p: "Portal", table: str, row_index: int) -> str | None:
    """The Web Description column is EMPTY in the collapsed table; the text only
    arrives when the row is expanded, which is one AJAX round-trip per row. Opt-in
    via --descriptions because it turns an 80-request job into an 8,000-request one."""
    try:
        resp = p.post({
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": table,
            "javax.faces.partial.execute": table,
            "javax.faces.partial.render": table,
            f"{table}_rowExpansion": "true",
            f"{table}_expandedRowIndex": str(row_index),
            f"{table}_encodeFeature": "true",
            f"{table}_skipChildren": "true",
            "ocrForm": "ocrForm",
        }, ajax=True)
    except Exception:
        return None
    # Pull only the reportResultTable update; the ViewState update would otherwise
    # be scraped in as description text.
    m = re.search(r'<update id="ocrForm:reportResultTable"><!\[CDATA\[(.*?)\]\]></update>', resp, re.S)
    body = m.group(1) if m else resp
    t = strip(htmllib.unescape(body))
    d = re.search(r"Web Description:\s*(.*)$", t, re.S)
    out = (d.group(1) if d else "").strip()
    return out or None


def to_doc(rec: dict, tab: str) -> dict:
    name = rec.get("covered_entity", "")
    aff = re.sub(r"[^\d]", "", rec.get("individuals_affected", "") or "")
    date = rec.get("breach_submission_date", "")
    iso = None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            iso = datetime.strptime(date, fmt).date().isoformat()
            break
        except ValueError:
            pass
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:70]
    blob = " ".join(str(rec.get(k) or "") for k in ("web_description", "breach_type", "breach_location"))
    return {
        "_id": f"hhs:{iso or date or 'na'}:{slug}" if slug else f"hhs:{tab}:{rec['_row_index']}",
        "source": "HHS OCR Breach Portal", "list_tab": tab,
        "covered_entity": name,
        "state": rec.get("state"),
        "covered_entity_type": rec.get("covered_entity_type"),
        "individuals_affected": int(aff) if aff else None,
        "breach_submission_date": date,
        "breach_submission_date_iso": iso,
        "breach_type": rec.get("breach_type"),
        "breach_location": rec.get("breach_location"),
        "business_associate_present": rec.get("business_associate_present"),
        "web_description": rec.get("web_description") or None,
        "is_hacking_it": bool(re.search(r"hacking|it incident", rec.get("breach_type", "") or "", re.I)),
        "ransomware_indicated": bool(RANSOM_RE.search(blob)),
        "mandatory_reporting": True,
        "reporting_threshold": "500+ individuals affected",
        "basis": "measured",
        "fetched_at": NOW,
    }


def scrape_tab(p: Portal, tab: str, limit_pages: int | None, descriptions: bool) -> list[dict]:
    html = p.get(ENTRY)                                  # 302s to the front page
    form, cmd = discover_nav(html, NAV_LABEL)
    html = p.post({form: form, cmd: cmd})                # -> breach_report_hip.jsf
    table, total, tabview = widget_ids(html)

    idx = TAB_ORDER.index(tab)
    if idx != 0:
        if not tabview:
            raise RuntimeError("no TabView found; cannot reach the archive")
        panels = tab_panels(html)
        if len(panels) <= idx:
            raise RuntimeError(f"expected {idx+1} tab panels, found {len(panels)}: {panels}")
        html = p.post({
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": tabview,
            "javax.faces.partial.execute": tabview,
            "javax.faces.partial.render": "ocrForm:breachReports ocrForm:results",
            "javax.faces.behavior.event": "tabChange",
            "javax.faces.partial.event": "tabChange",
            # The PANEL CLIENT ID, not the index. An index here redirects to
            # error_breach.jsf with no explanation.
            f"{tabview}_newTab": panels[idx],
            f"{tabview}_tabindex": str(idx),
            f"{tabview}_activeIndex": str(idx),
            "ocrForm": "ocrForm",
        }, ajax=True)
        m = re.search(r'PrimeFaces\.cw\("DataTable","[^"]*",\{id:"([^"]+)".*?rowCount:(\d+)', html, re.S)
        if m:
            table, total = m.group(1), int(m.group(2))
        else:
            raise RuntimeError("tab switch returned no DataTable config")

    pages = (total + PAGE_ROWS - 1) // PAGE_ROWS
    if limit_pages:
        pages = min(pages, limit_pages)
    print(f"  [{tab}] {total:,} records, {pages} page(s) of {PAGE_ROWS}")

    recs, seen = [], set()
    for pg in range(pages):
        if pg == 0:
            frag = html
        else:
            frag = p.post({
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": table,
                "javax.faces.partial.execute": table,
                "javax.faces.partial.render": table,
                "javax.faces.behavior.event": "page",
                "javax.faces.partial.event": "page",
                f"{table}_pagination": "true",
                f"{table}_first": str(pg * PAGE_ROWS),
                f"{table}_rows": str(PAGE_ROWS),
                f"{table}_skipChildren": "true",
                f"{table}_encodeFeature": "true",
                "ocrForm": "ocrForm",
            }, ajax=True)
        page_recs = parse_rows(frag)
        if descriptions:
            for r in page_recs:
                r["web_description"] = fetch_description(p, table, r["_row_index"]) or ""
                time.sleep(0.25)
        fresh = 0
        for r in page_recs:
            d = to_doc(r, tab)
            if d["_id"] in seen:
                continue
            seen.add(d["_id"]); recs.append(d); fresh += 1
        print(f"    page {pg+1}/{pages}: {len(page_recs)} rows, {fresh} new (total {len(recs):,})")
        if not page_recs:
            print("    (empty page — stopping early)")
            break
        time.sleep(0.6)
    return recs


def val(args, name, default=None):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    only = val(args, "--tab")
    pages = val(args, "--pages")
    pages = int(pages) if pages else (1 if dry else None)
    descriptions = "--descriptions" in args
    want = [only] if only in TAB_ORDER else list(SCRAPE_TABS)
    if descriptions:
        print("--descriptions: expanding every row (1 extra request each). This is slow.\n")

    p = Portal()
    recs = []
    for tab in want:
        try:
            recs.extend(scrape_tab(p, tab, pages, descriptions))
        except Exception as e:
            print(f"  [{tab}] FAILED: {str(e)[:160]}")
            p = Portal()        # fresh session before trying the next tab

    if not recs:
        print("\nno records scraped — the portal markup has probably changed. "
              "Re-run the probes in the module docstring.")
        return 1

    if "--ransomware-only" in args:
        before = len(recs)
        recs = [r for r in recs if r["ransomware_indicated"]]
        print(f"\nfiltered to ransomware-indicated: {len(recs):,} of {before:,}")

    desc = sum(1 for r in recs if r["web_description"])
    if not descriptions:
        print("\nNOTE: web_description is empty without --descriptions (the portal only sends it on "
              "row expansion), so ransomware_indicated falls back to keyword hits on the other "
              "columns and will read ~0%. Use breach_type == 'Hacking/IT Incident' as the proxy, or "
              "re-run with --descriptions to name the strain.")
    hack = sum(1 for r in recs if r["is_hacking_it"])
    ransom = sum(1 for r in recs if r["ransomware_indicated"])
    aff = [r["individuals_affected"] for r in recs if r["individuals_affected"]]
    print(f"\n{len(recs):,} records | hacking/IT {hack:,} ({100*hack/len(recs):.0f}%) | "
          f"ransomware-indicated {ransom:,} ({100*ransom/len(recs):.0f}%) | "
          f"with description {desc:,}")
    if aff:
        aff.sort()
        print(f"individuals affected: median {aff[len(aff)//2]:,} | "
              f"max {aff[-1]:,} | total {sum(aff):,}")
    yrs = {}
    for r in recs:
        if r["breach_submission_date_iso"]:
            yrs[r["breach_submission_date_iso"][:4]] = yrs.get(r["breach_submission_date_iso"][:4], 0) + 1
    if yrs:
        print("by year: " + ", ".join(f"{k} {v}" for k, v in sorted(yrs.items())))

    print("\nsample:")
    for r in recs[:5]:
        print(f"  {(r['covered_entity'] or '')[:44]:44} {r['state'] or '':3} "
              f"{(r['individuals_affected'] or 0):>9,} {r['breach_submission_date_iso'] or '':10} "
              f"{(r['breach_type'] or '')[:26]}")

    if dry:
        print("\n[dry-run] first page only, nothing written.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(recs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {len(recs):,} docs -> {OUT}")
    print("note: HHS covers ALL breach types at 500+ individuals, not just ransomware and not "
          "small practices. Keep it independent of `victims` so capture-recapture stays valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
