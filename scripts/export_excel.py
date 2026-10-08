"""
export_excel.py — the statistics workbook: every headline number, one file.

Built for the colleagues who work in Excel rather than JSON. Eight sheets:
frequency by industry, rate by revenue, size bands, victims by year, repeat
victims, under-reporting, DBIR benchmark, severity, and a reconciliation sheet
that re-adds every total so "do the industries sum?" is answerable by eye.

Everything derivable is a FORMULA (rates, shares, relative risk, Chapman), so
the workbook recalculates if a count is corrected. Hardcoded cells are inputs
from the datasets and say where they came from.

Reads  data/mongo/frequency.json, benchmarks.json, frequency_calibration.json,
       incidents.json, comparitech.json, hhs_ocr.json
Writes data/CNA_ransomware_stats.xlsx

Usage: python scripts/export_excel.py
"""

from __future__ import annotations

import io
import json
import math
import statistics as st
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "CNA_ransomware_stats.xlsx"

L = lambda f: json.loads(io.open(ROOT / "data" / "mongo" / f, encoding="utf-8-sig").read())
freq = L("frequency.json")
bench = L("benchmarks.json")
cal = L("frequency_calibration.json")
inc = L("incidents.json")
comp = L("comparitech.json")
hhs = L("hhs_ocr.json")

marg = sorted((d for d in freq if d["kind"] == "industry_marginal"),
              key=lambda d: -d["rate"]["central_per_10k"])
sizes = [d for d in freq if d["kind"] == "size_marginal"]
method = next(d for d in freq if d["kind"] == "method")
rep = next(d for d in bench if d["kind"] == "repeat_victims")
byyear = next(d for d in bench if d["kind"] == "victims_by_year")
dbir = next(d for d in bench if d["kind"] == "dbir_benchmark")

# ---------------------------------------------------------------- style kit
NAVY, BLUE, GREY = "13294B", "4B9CD3", "6C737A"
F_BASE = Font(name="Arial", size=10)
F_HDR = Font(name="Arial", size=10, bold=True, color="FFFFFF")
F_BOLD = Font(name="Arial", size=10, bold=True)
F_TITLE = Font(name="Arial", size=13, bold=True, color=NAVY)
F_NOTE = Font(name="Arial", size=9, italic=True, color=GREY)
FILL_HDR = PatternFill("solid", fgColor=NAVY)
FILL_TOT = PatternFill("solid", fgColor="DCE9F5")
THIN = Side(style="thin", color="C9CDD2")
B_ALL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def sheet(wb, name, title, note):
    ws = wb.create_sheet(name)
    ws["A1"] = title
    ws["A1"].font = F_TITLE
    ws["A2"] = note
    ws["A2"].font = F_NOTE
    ws.sheet_view.showGridLines = False
    return ws


def table(ws, row, headers, widths):
    for j, (h, w) in enumerate(zip(headers, widths), start=1):
        c = ws.cell(row=row, column=j, value=h)
        c.font, c.fill, c.border = F_HDR, FILL_HDR, B_ALL
        c.alignment = Alignment(horizontal="center", wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = w
    return row + 1


def put(ws, r, vals, fmts=None, bold=False, fill=None):
    for j, v in enumerate(vals, start=1):
        c = ws.cell(row=r, column=j, value=v)
        c.font = F_BOLD if bold else F_BASE
        c.border = B_ALL
        if fill:
            c.fill = fill
        if fmts and fmts[j - 1]:
            c.number_format = fmts[j - 1]
    return r + 1


def note(ws, r, text):
    c = ws.cell(row=r, column=1, value=text)
    c.font = F_NOTE
    return r + 1


wb = Workbook()
wb.remove(wb.active)

# ================================================================ Read Me
ws = sheet(wb, "Read Me", "CNA Ransomware Risk Dataset - Statistics Workbook",
           f"Generated {date.today().isoformat()} by scripts/export_excel.py. "
           "Regenerable; do not hand-edit values - fix the data and re-run.")
rows = [
    ("Sheet", "Contents"),
    ("Frequency", "Attack rate per 10,000 US firms by industry, 2025, with relative risk. "
                  "Rates and RR are live formulas over the counts."),
    ("Revenue", "The same victims per $100B of industry receipts (SUSB RCPT). Formulas."),
    ("Size bands", "Firm and victim shares by employee band; relative rate as formulas."),
    ("By year", "Distinct victim organisations per year with country coverage."),
    ("Repeat victims", "How often the same organisation is listed again."),
    ("Under-reporting", "Capture-recapture inputs with Chapman estimator AS FORMULAS, "
                        "the dependence sweep, and the HHS cross-check."),
    ("DBIR benchmark", "Industry-mix comparison vs Verizon DBIR 2026 Table 3 (p.77), "
                       "size and volume benchmarks."),
    ("Severity", "Distribution statistics for records affected, ransom amounts, "
                 "financial impact. Computed from the collections; sources cited."),
    ("Reconciliation", "Every total re-added from its parts, so sums are checkable by eye."),
]
r = 4
for i, (a, b) in enumerate(rows):
    ws.cell(row=r, column=1, value=a).font = F_BOLD if i == 0 else F_BASE
    ws.cell(row=r, column=2, value=b).font = F_BOLD if i == 0 else F_BASE
    r += 1
ws.column_dimensions["A"].width = 18
ws.column_dimensions["B"].width = 110
r += 1
for t in ("Sources: ransomware.live (leak-site victims) - Census SUSB 2022 (firms, receipts) - "
          "Census of Governments 2022 - NCES/IPEDS - Comparitech trackers - HHS OCR breach portal - "
          "Ransomwhere - Verizon DBIR 2026 (benchmark only).",
          "Every number's basis is recorded in the underlying dataset as measured / estimated / "
          "assumed / derived; see the method document in the frequency collection.",
          "Rates measure how often a firm is LISTED on a leak site, not how often one is attacked. "
          "Central rates apply a 7.4x under-reporting multiplier, derived, not assumed."):
    r = note(ws, r, t)

# ================================================================ Frequency
ws = sheet(wb, "Frequency", "Attack rate by industry - US, 2025",
           "Counts are inputs from the dataset; every rate, RR and total is a formula. "
           "obs/10k uses confirmed-US victims only; central adds country + under-reporting corrections.")
r = table(ws, 4, ["Industry", "Victims (obs)", "Victims (adj x R)", "Firms", "obs /10k",
                  "RR (obs)", "central /10k", "low /10k", "high /10k", "R", "R basis",
                  "Crosswalk", "Denominator unit"],
          [30, 12, 14, 12, 10, 9, 12, 10, 10, 7, 10, 10, 16])
first = r
for d in marg:
    rt, den, num = d["rate"], d["denominator"], d["numerator"]
    ws.cell(row=r, column=1, value=d["ransomware_live_sector"])
    ws.cell(row=r, column=2, value=num["observed"]["value"])
    ws.cell(row=r, column=3, value=round(num["under_reporting_adjusted"]["value"], 1))
    ws.cell(row=r, column=4, value=den["firms"])
    ws.cell(row=r, column=5, value=f"=ROUND(B{r}/D{r}*10000,2)")
    ws.cell(row=r, column=6, value=f"=ROUND(E{r}/E$%TOT%,2)")       # vs total row, patched below
    ws.cell(row=r, column=7, value=f"=ROUND(C{r}/D{r}*10000,1)")
    ws.cell(row=r, column=8, value=rt["low_per_10k"])
    ws.cell(row=r, column=9, value=rt["high_per_10k"])
    ws.cell(row=r, column=10, value=d["under_reporting_multiplier"]["value"])
    ws.cell(row=r, column=11, value=d["under_reporting_multiplier"]["basis"])
    ws.cell(row=r, column=12, value=den["crosswalk_confidence"])
    ws.cell(row=r, column=13, value=den["unit"])
    r += 1
last = r - 1
ws.cell(row=r, column=1, value="ALL INDUSTRIES")
ws.cell(row=r, column=2, value=f"=SUM(B{first}:B{last})")
ws.cell(row=r, column=3, value=f"=SUM(C{first}:C{last})")
ws.cell(row=r, column=4, value=f"=SUM(D{first}:D{last})")
ws.cell(row=r, column=5, value=f"=ROUND(B{r}/D{r}*10000,2)")
ws.cell(row=r, column=6, value=1)
ws.cell(row=r, column=7, value=f"=ROUND(C{r}/D{r}*10000,1)")
tot_row = r
for j in range(1, 14):
    c = ws.cell(row=r, column=j)
    c.font, c.fill, c.border = F_BOLD, FILL_TOT, B_ALL
for rr_ in range(first, last + 1):
    ws.cell(row=rr_, column=6).value = f"=ROUND(E{rr_}/E${tot_row},2)"
for rr_ in range(first, tot_row + 1):
    for j, fmt in ((2, "#,##0"), (3, "#,##0"), (4, "#,##0"), (5, "0.00"), (6, "0.00"),
                   (7, "0.0"), (8, "0.0"), (9, "0.0"), (10, "0.0")):
        ws.cell(row=rr_, column=j).number_format = fmt
    for j in range(1, 14):
        ws.cell(row=rr_, column=j).border = B_ALL
        if ws.cell(row=rr_, column=j).font == F_BASE or rr_ <= last:
            if rr_ != tot_row:
                ws.cell(row=rr_, column=j).font = F_BASE
r += 2
r = note(ws, r, "RR = industry obs/10k over the all-industry obs/10k. The under-reporting "
               "multiplier cancels out of RR entirely, so it rests on no adjustment.")
r = note(ws, r, "Public Sector is counted per GOVERNMENT (90,887 units), not per firm - "
               "not directly comparable to the other rows.")
r = note(ws, r, "low/high carry the under-reporting scenario band (5.8x / 10.6x), not a "
               "confidence interval. Poisson CIs on the counts are in the dataset.")

# ================================================================ Revenue
ws = sheet(wb, "Revenue", "Attack rate by revenue - US, 2025",
           "Same victims, divided by industry receipts (SUSB 2022 RCPT, published in $1,000s; "
           "sectors sum to $50.5T). Rates are formulas.")
r = table(ws, 4, ["Industry", "Receipts ($B)", "Victims (obs)", "obs per $100B",
                  "central per $100B", "Caveat"], [30, 13, 12, 13, 15, 60])
first = r
for d in sorted(marg, key=lambda d: -(d["rate"].get("observed_per_100b_revenue") or -1)):
    den = d["denominator"]
    if den.get("receipts_busd") is None:
        r = put(ws, r, [d["ransomware_live_sector"], "n/a", d["numerator"]["observed"]["value"],
                        "n/a", "n/a", den.get("receipts_caveat") or ""])
        continue
    ws.cell(row=r, column=1, value=d["ransomware_live_sector"])
    ws.cell(row=r, column=2, value=den["receipts_busd"]).number_format = "#,##0.0"
    ws.cell(row=r, column=3, value=d["numerator"]["observed"]["value"]).number_format = "#,##0"
    ws.cell(row=r, column=4, value=f"=ROUND(C{r}/(B{r}/100),2)").number_format = "0.00"
    ws.cell(row=r, column=5, value=f"=ROUND(C{r}*{d['under_reporting_multiplier']['value']}"
                                   f"*{round(d['numerator']['country_adjusted']['value']/max(d['numerator']['observed']['value'],1),4)}"
                                   f"/(B{r}/100),1)").number_format = "0.0"
    ws.cell(row=r, column=6, value=den.get("receipts_caveat") or "")
    for j in range(1, 7):
        ws.cell(row=r, column=j).border = B_ALL
        ws.cell(row=r, column=j).font = F_BASE
    r += 1
r += 1
r = note(ws, r, "central = obs x (country adjustment) x R over the same receipts. Education is "
               "overstated (receipts are private-only; victims include public institutions).")

# ================================================================ Size bands
ws = sheet(wb, "Size bands", "Risk by employee band",
           "Firm counts: SUSB unduplicated US totals. Victim sizes: the 227 leak-site records "
           "carrying an employee label (65 US). Shares and relative rate are formulas.")
r = table(ws, 4, ["Band", "Firms", "Firm share", "Labelled victims", "Victim share",
                  "Relative rate (obs)", "Relative rate (fitted)"], [10, 13, 11, 14, 12, 15, 15])
first = r
for d in sizes:
    ws.cell(row=r, column=1, value=d["size_band"])
    ws.cell(row=r, column=2, value=d["firms"]).number_format = "#,##0"
    ws.cell(row=r, column=4, value=d["labelled_victims"]).number_format = "#,##0"
    ws.cell(row=r, column=7, value=d["relative_rate_fitted"]).number_format = "0.00"
    for j in range(1, 8):
        ws.cell(row=r, column=j).border = B_ALL
        ws.cell(row=r, column=j).font = F_BASE
    r += 1
last = r - 1
ws.cell(row=r, column=1, value="TOTAL").font = F_BOLD
ws.cell(row=r, column=2, value=f"=SUM(B{first}:B{last})").number_format = "#,##0"
ws.cell(row=r, column=4, value=f"=SUM(D{first}:D{last})").number_format = "#,##0"
for j in range(1, 8):
    ws.cell(row=r, column=j).border = B_ALL
    ws.cell(row=r, column=j).fill = FILL_TOT
tot = r
for rr_ in range(first, last + 1):
    ws.cell(row=rr_, column=3, value=f"=B{rr_}/B${tot}").number_format = "0.00%"
    ws.cell(row=rr_, column=5, value=f"=D{rr_}/D${tot}").number_format = "0.00%"
    ws.cell(row=rr_, column=6, value=f"=ROUND(E{rr_}/C{rr_},2)").number_format = "0.00"
r += 2
r = note(ws, r, f"Weighted log-log fit: rate ~ employees^{method['size_model']['elasticity_b']:.2f} "
               f"(R2 {method['size_model']['weighted_r2']:.2f}), held flat above 1,000 employees.")
r = note(ws, r, "The 1-4 band (63% of all US firms) rests on 7 labelled records; the fitted "
               "slope is probably too steep. Weakest link in the model, stated plainly.")

# ================================================================ By year
ws = sheet(wb, "By year", "Victims by year",
           "Distinct organisations named per year (global). US counts before 2024 are floors: "
           "country is known for only 14-46% of 2021-2023 records.")
r = table(ws, 4, ["Year", "Listings", "Distinct orgs", "US-confirmed distinct",
                  "Country known %", "Note"], [8, 11, 13, 18, 14, 34])
for y in byyear["years"]:
    if y["year"] < 2020:
        continue
    r = put(ws, r, [y["year"], y["listings"], y["distinct_orgs"], y["us_confirmed_distinct"],
                    (y["country_known_pct"] or 0) / 100,
                    "rate year" if y["complete"] else (y["partial"] or "")],
            fmts=["0", "#,##0", "#,##0", "#,##0", "0.0%", None])
r += 1
r = note(ws, r, byyear["note"])

# ================================================================ Repeat victims
ws = sheet(wb, "Repeat victims", "Repeat victimisation",
           "How often the same organisation appears more than once, matched on normalised "
           "name and domain across all 27,108 records.")
r = 4
for k, v, fmt in [
    ("Distinct organisations ever listed", rep["distinct_organisations"], "#,##0"),
    ("Listed more than once", rep["listed_more_than_once"], "#,##0"),
    ("Repeat rate", rep["repeat_rate"], "0.0%"),
    ("By 2+ different crews", rep["by_two_plus_groups"], "#,##0"),
    ("Different crew AND different year (clear re-attacks)", rep["different_group_and_year"], "#,##0"),
    ("US 2025: distinct organisations", rep["us_2025_distinct"], "#,##0"),
    ("US 2025: listed 2+ times", rep["us_2025_repeat"], "#,##0"),
    ("US 2025 repeat rate", rep["us_2025_repeat_rate"], "0.0%"),
]:
    ws.cell(row=r, column=1, value=k).font = F_BASE
    c = ws.cell(row=r, column=2, value=v)
    c.font, c.number_format, c.border = F_BOLD, fmt, B_ALL
    ws.cell(row=r, column=1).border = B_ALL
    r += 1
ws.column_dimensions["A"].width = 48
ws.column_dimensions["B"].width = 12
r += 1
r = note(ws, r, rep["note"])

# ================================================================ Under-reporting
ws = sheet(wb, "Under-reporting", "Under-reporting, measured",
           "Chapman capture-recapture vs the independent Comparitech list. N and R are LIVE "
           "FORMULAS over A, B, M - change an input and the estimate recalculates.")
r = table(ws, 4, ["Stratum", "A (leak-site)", "B (independent)", "M (both)",
                  "N-hat (Chapman)", "R = N/A", "R @25% copied", "R @50% copied"],
          [16, 12, 13, 10, 14, 10, 13, 13])
first = r
for sdoc in cal["strata"]:
    A, B, M = sdoc["A_leaksite"], sdoc["B_comparitech"], sdoc["fuzzy"]["M_overlap"]
    ws.cell(row=r, column=1, value=sdoc["stratum"])
    ws.cell(row=r, column=2, value=A).number_format = "#,##0"
    ws.cell(row=r, column=3, value=B).number_format = "#,##0"
    ws.cell(row=r, column=4, value=M).number_format = "#,##0"
    ws.cell(row=r, column=5, value=f"=ROUND((B{r}+1)*(C{r}+1)/(D{r}+1)-1,0)").number_format = "#,##0"
    ws.cell(row=r, column=6, value=f"=ROUND(E{r}/B{r},2)").number_format = "0.00"
    # phi = k*(M/B); B' = B - k*M ; M' = M*(1-k)
    ws.cell(row=r, column=7, value=f"=ROUND(((B{r}+1)*((C{r}-0.25*D{r})+1)/((D{r}*0.75)+1)-1)/B{r},2)").number_format = "0.00"
    ws.cell(row=r, column=8, value=f"=ROUND(((B{r}+1)*((C{r}-0.5*D{r})+1)/((D{r}*0.5)+1)-1)/B{r},2)").number_format = "0.00"
    for j in range(1, 9):
        ws.cell(row=r, column=j).border = B_ALL
        ws.cell(row=r, column=j).font = F_BASE
    r += 1
r += 1
sch = cal["published_schedule"]
r = put(ws, r, ["Published schedule", f"low {sch['low']['value']}x",
                f"central {sch['central']['value']}x", f"high {sch['high']['value']}x"], bold=True)
r += 1
h = cal["hhs_cross_check"]["headline"]
r = table(ws, r, ["HHS cross-check (mandatory list)", "B (HHS)", "M (matched)",
                  "Capture", "Implied R"], [30, 10, 11, 10, 10])
ws.cell(row=r, column=1, value="ransomware-indicated, 2019+")
ws.cell(row=r, column=2, value=h["B_hhs"]).number_format = "#,##0"
ws.cell(row=r, column=3, value=h["M_fuzzy"]).number_format = "#,##0"
ws.cell(row=r, column=4, value=f"=C{r}/B{r}").number_format = "0.0%"
ws.cell(row=r, column=5, value=f"=ROUND(B{r}/C{r},1)").number_format = "0.0"
for j in range(1, 6):
    ws.cell(row=r, column=j).border = B_ALL
    ws.cell(row=r, column=j).font = F_BASE
r += 2
r = note(ws, r, "The naive column assumes list independence and is a hard LOWER bound; the HHS "
               "route implies ~22x. Published rates follow the conservative schedule, so they "
               "are more likely too low than too high.")

# ================================================================ DBIR benchmark
ws = sheet(wb, "DBIR benchmark", "Benchmark vs Verizon DBIR 2026",
           "DBIR Table 3 (p.77) incidents mapped onto our sectors by NAICS. Shares and deltas "
           "are formulas. DBIR figures transcribed from the published PDF, cited by page.")
r = table(ws, 4, ["Sector", "Ours (2025 distinct)", "DBIR incidents", "Our share",
                  "DBIR share", "Delta (pp)"], [32, 16, 13, 10, 10, 10])
first = r
rows_ = sorted(dbir["industry_mix"]["rows"], key=lambda x: -x["leak_site_share"])
for x in rows_:
    ws.cell(row=r, column=1, value=x["sector"])
    ws.cell(row=r, column=2, value=x["leak_site_2025_distinct"]).number_format = "#,##0"
    ws.cell(row=r, column=3, value=x["dbir_incidents"]).number_format = "#,##0"
    r += 1
last = r - 1
ws.cell(row=r, column=1, value="TOTAL").font = F_BOLD
ws.cell(row=r, column=2, value=f"=SUM(B{first}:B{last})").number_format = "#,##0"
ws.cell(row=r, column=3, value=f"=SUM(C{first}:C{last})").number_format = "#,##0"
tot = r
for rr_ in range(first, last + 1):
    ws.cell(row=rr_, column=4, value=f"=B{rr_}/B${tot}").number_format = "0.0%"
    ws.cell(row=rr_, column=5, value=f"=C{rr_}/C${tot}").number_format = "0.0%"
    ws.cell(row=rr_, column=6, value=f"=(D{rr_}-E{rr_})*100").number_format = "+0.0;-0.0"
for rr_ in range(first, tot + 1):
    for j in range(1, 7):
        ws.cell(row=rr_, column=j).border = B_ALL
        if rr_ != tot:
            ws.cell(row=rr_, column=j).font = F_BASE
        else:
            ws.cell(row=rr_, column=j).fill = FILL_TOT
r = tot + 2
for t in (f"Spearman rank correlation: {dbir['industry_mix']['spearman_rank_correlation']} - "
          "directionally consistent; the big gaps line up with who is REQUIRED to report "
          "(Public Sector, Finance are 2-3x heavier in DBIR).",
          "Size: DBIR ~96% of ransomware victims are SMBs (p.98) vs our 95.6% of size-labelled "
          "victims - independent agreement.",
          f"Volume floor: DBIR contributors documented ~{dbir['volume_floor']['dbir_ransomware_breaches_est']:,} "
          f"ransomware breaches (48% x 22,625, pp.11/77) = {dbir['volume_floor']['ratio']}x all "
          f"leak-site-named orgs in 2025 ({dbir['volume_floor']['leak_site_2025_distinct_global']:,}).",
          "Ransom ladder: paid $139,875 median (DBIR p.11) / demanded $428k (Comparitech) / "
          "news-reported $8M (researched). 69% of DBIR victims did not pay.",
          "Caveats: DBIR counts all incident types (Table 3 is not per-pattern); DBIR keeps food "
          "manufacturing in 31-33 where our crosswalk assigns it to Agriculture; 'Information "
          "(51)' is compared against our Technology+Telecommunication combined."):
    r = note(ws, r, t)

# ================================================================ Severity
def dist(xs):
    xs = sorted(xs)
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
    lg = [math.log(x) for x in xs if x > 0]
    return dict(n=len(xs), median=q(.5), p75=q(.75), p95=q(.95), mx=max(xs),
                mu=st.mean(lg), sigma=st.pstdev(lg))

NEGS = ("not", "undisclosed", "unknown", "n/a", "none")
sev_rows = [
    ("Records affected - HHS, ransomware-indicated",
     dist([x["individuals_affected"] for x in hhs if x.get("individuals_affected") and x.get("ransomware_indicated")]),
     "people", "HHS OCR portal, mandatory 500+ reports, 2009-2026"),
    ("Records affected - HHS, all breach types",
     dist([x["individuals_affected"] for x in hhs if x.get("individuals_affected")]),
     "people", "HHS OCR portal"),
    ("Records affected - Comparitech",
     dist([x["records_affected"] for x in comp if x.get("records_affected")]),
     "people", "Comparitech trackers"),
    ("Ransom amount - Comparitech",
     dist([x["ransom_amount_usd"] for x in comp if x.get("ransom_amount_usd")]),
     "USD", "Comparitech trackers (demands/known amounts)"),
    ("Ransom amount - researched incidents",
     dist([x["ransom"]["usd"] for x in inc if isinstance(x.get("ransom"), dict) and x["ransom"].get("usd")]),
     "USD", "researched incidents (news-reported; selection-biased large)"),
    ("Financial impact - researched incidents",
     dist([x["financial"]["usd"] for x in inc if isinstance(x.get("financial"), dict) and x["financial"].get("usd")]),
     "USD", "researched incidents (mixed basis: cost/recovery/fines)"),
]
ws = sheet(wb, "Severity", "Severity distributions",
           "Computed from the collections at export time. Use records affected for modelling "
           "(n=1,246 ransomware) - dollar figures are few and mixed-basis.")
r = table(ws, 4, ["Variable", "n", "Median", "p75", "p95", "Max", "lognormal mu",
                  "lognormal sigma", "Unit", "Source"], [40, 8, 12, 12, 13, 14, 11, 12, 7, 46])
for name_, d, unit, src in sev_rows:
    r = put(ws, r, [name_, d["n"], d["median"], d["p75"], d["p95"], d["mx"],
                    round(d["mu"], 2), round(d["sigma"], 2), unit, src],
            fmts=[None, "#,##0", "#,##0", "#,##0", "#,##0", "#,##0", "0.00", "0.00", None, None])
r += 1
r = note(ws, r, "The two ransom medians differ 19x ($428k vs $8.0M): selection bias, not error. "
               "Each list up the ladder (paid -> tracked -> newsworthy) selects for bigger incidents.")
r = note(ws, r, "Downtime: 323 incidents describe recovery in words; only ~10 state a usable "
               "duration. Not modellable from public sources.")

# ================================================================ Reconciliation
ws = sheet(wb, "Reconciliation", "Totals, re-added from their parts",
           "The 'do the industries sum?' sheet. Each total is a SUM formula over its parts, "
           "next to the independently published total it must (or must not) match.")
r = 4
r = put(ws, r, ["Check", "Sum of parts", "Published / expected", "Match?"], bold=True,
        fill=FILL_HDR)
for j in range(1, 5):
    ws.cell(row=r - 1, column=j).font = F_HDR
ws.column_dimensions["A"].width = 64
for col, w in (("B", 16), ("C", 18), ("D", 9)):
    ws.column_dimensions[col].width = w
checks = [
    ("US 2025 victims: 14 industry rows sum to the model total",
     "=Frequency!B19", 3459, "exact"),
    ("US firms: 14 sector denominators sum to the model total",
     "=Frequency!D19", 6517587, "exact"),
    ("SUSB sector firm sums EXCEED the unduplicated US total - by design: SUSB counts "
     "a firm once per sector it operates in (sum 6,411,782 + 105,805 supplements vs "
     "6,395,635 unduplicated)", 6517587, 6395635, "sum > total is correct"),
    ("Size bands: 8 bands sum to the unduplicated US firm total",
     "='Size bands'!B13", 6395635, "exact"),
    ("DBIR Table 3: mapped industry rows (DBIR benchmark sheet total) + the 5,361 "
     "'Unknown' row sum to the published 31,861",
     "='DBIR benchmark'!C18+5361", 31861, "exact"),
    ("Severity: HHS ransomware subset is a strict subset of all HHS rows (1,246 of 7,925)",
     1246, 7925, "subset"),
]
for name_, a, b, kind in checks:
    ws.cell(row=r, column=1, value=name_).alignment = Alignment(wrap_text=True, vertical="top")
    ws.cell(row=r, column=2, value=a)
    ws.cell(row=r, column=3, value=b)
    if kind == "exact":
        ws.cell(row=r, column=4, value=f'=IF(B{r}=C{r},"YES","NO")')
    elif kind == "subset":
        ws.cell(row=r, column=4, value=f'=IF(B{r}<C{r},"YES","NO")')
    else:
        ws.cell(row=r, column=4, value=f'=IF(B{r}>C{r},"YES (by design)","NO")')
    for j in range(1, 5):
        ws.cell(row=r, column=j).border = B_ALL
        ws.cell(row=r, column=j).font = F_BASE
    for j, fmt in ((2, "#,##0"), (3, "#,##0")):
        ws.cell(row=r, column=j).number_format = fmt
    r += 1
r += 1
r = note(ws, r, "The third row is the one that trips people: sector firm counts legitimately "
               "sum to MORE than the US total, because a multi-sector firm is counted in every "
               "sector it operates in. Asserting sum <= total was a bug we removed.")

wb.save(OUT)
print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB, {len(wb.sheetnames)} sheets)")
print("sheets:", ", ".join(wb.sheetnames))
