"""
build_frequency.py — the ransomware FREQUENCY MODEL (US).

Turns attack counts into attack RATES: P(a firm is listed on a ransomware leak
site in a year), segmented by industry x employee band.

    observed -> country-adjusted -> size-allocated -> under-reporting-adjusted -> rate
    [measured]     [estimated]        [estimated]          [estimated]          [derived]

Every number carries a `basis` (measured|estimated|assumed|derived) and, where it
is not directly measured, `assumption_ids` resolving into the `method` doc. That
is what makes the table auditable rather than a pile of plausible numbers.

Reads  data/raw/sector_*.json            (numerator)
       data/mongo/frequency_exposure.json (denominator, from fetch_exposure.py)
       data/mongo/frequency_calibration.json (optional, from estimate_underreporting.py)
       data/naics_crosswalk.json
Writes data/mongo/frequency.json

Usage:
  python scripts/build_frequency.py --dry-run
  python scripts/build_frequency.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INDUSTRIES = ROOT / "data" / "industries.json"
CROSSWALK = ROOT / "data" / "naics_crosswalk.json"
EXPOSURE = ROOT / "data" / "mongo" / "frequency_exposure.json"
CALIBRATION = ROOT / "data" / "mongo" / "frequency_calibration.json"
OUT = ROOT / "data" / "mongo" / "frequency.json"

EXPOSURE_YEAR = 2025          # the only year with complete 12-month sector coverage
# Under-reporting schedule. These are FALLBACKS used only when
# data/mongo/frequency_calibration.json is absent; estimate_underreporting.py
# derives them from a capture-recapture dependence sweep and overrides all three.
DEFAULT_R = 7.0
R_LOW, R_HIGH = 5.4, 12.0
NOW = datetime.now(timezone.utc).isoformat()

BANDS = [("1-4",1,4),("5-9",5,9),("10-19",10,19),("20-49",20,49),
         ("50-99",50,99),("100-499",100,499),("500-999",500,999),("1000+",1000,None)]
BAND_MID = {"1-4":2.5,"5-9":7,"10-19":14.5,"20-49":34.5,
            "50-99":74.5,"100-499":300,"500-999":750,"1000+":2500}
SATURATION_BAND = "1000+"     # power law is capped above here (see A-SATURATION)

# Hazard/exposure families, mirrored from FAMILIES in scripts/export_mongo.js.
# Order matters: first match wins, exactly as familyOf() does there. Kept in sync
# by hand; both are short and change rarely.
FAMILIES = [
    ("Third-Party & Supply Chain", r"third party|supply chain|vendor|outsourc|msp|concentration"),
    ("Regulatory & Legal", r"regulat|legal|complian|contractual|litigat|sanction|privacy law"),
    ("Insider & Workforce", r"insider|workforce|human factor|credential|privileged access|"
                            r"student originated|social engineer"),
    ("Initial Access", r"initial access|entry|intrusion|attack vector|exploitation"),
    ("Extortion & Impact", r"extortion|ransom|leak|exfiltrat|double|encryption|impact tactic|harassment"),
    ("OT & Operational Disruption", r"\bot\b|ics|scada|operational technology|physical|safety|"
                                    r"production|availability|disruption|outage|network"),
    ("Data & IP Confidentiality", r"confidential|intellectual property|trade secret|source code|"
                                  r"data theft|sensitive data|pii|phi"),
    ("Business Interruption", r"business interruption|project delay|revenue|financial loss|liquidity"),
]
FAMILY_RE = [(name, re.compile(pat, re.I)) for name, pat in FAMILIES]
PROCESS_FAMILIES = {"OT & Operational Disruption", "Business Interruption"}


def family_of(key: str) -> str:
    for name, rx in FAMILY_RE:
        if rx.search(key or ""):
            return name
    return "Other"


def process_dependence() -> dict:
    """Share of an industry's hazard+exposure categories falling in the two
    operational families. A RELATIVE index of how much the industry's risk is about
    processes stopping rather than data leaking. Explicitly NOT multiplied into
    frequency: there is no evidence base for a coefficient, and conflating a
    severity-flavoured construct with frequency is exactly the error to avoid."""
    out = {}
    try:
        inds = json.loads(INDUSTRIES.read_text(encoding="utf-8").lstrip("\ufeff"))
    except Exception:
        return out
    for ind in inds:
        # Pool categories AND subcategories. Top-level categories alone give only
        # 10-16 observations per industry, which makes the index hostage to how many
        # headings an industry happens to have: it scored Energy 0.18 (below
        # Healthcare) and Financial Services a degenerate 0.00. Pooling the leaves
        # gives 60-145 observations and ranks Manufacturing/Transportation/Energy
        # top, which is both stable and face-valid.
        cats = []
        for key in ("hazard_categories", "exposure_categories"):
            for c in (ind.get(key) or []):
                cats.append(c.get("category", ""))
                cats.extend(c.get("subcategories") or [])
        if not cats:
            continue
        fams = [family_of(c) for c in cats]
        hit = sum(1 for f in fams if f in PROCESS_FAMILIES)
        out[ind.get("ransomware_live_sector", "")] = {
            "index": round(hit / len(fams), 3),
            "categories_total": len(fams), "categories_operational": hit,
            "granularity": "categories + subcategories pooled",
            "families_counted": sorted(PROCESS_FAMILIES),
            "basis": "derived",
            "note": "relative index only; NOT a frequency multiplier",
        }
    return out


# ---------------------------------------------------------------- normalisation
SUFFIX = re.compile(r"\b(inc|inc\.|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|"
                    r"plc|group|holdings|holding|the|gmbh|srl|sa|bv|ag|pty|llp)\b", re.I)

def norm_name(s: str) -> str:
    s = re.sub(r"^www\.", "", (s or "").strip().lower())
    s = re.sub(r"\.(com|net|org|co|io|us|gov|edu|info|biz)(\.[a-z]{2})?$", "", s)
    s = SUFFIX.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def dom_root(domain: str) -> str:
    d = re.sub(r"^www\.", "", (domain or "").strip().lower())
    return d.split("/")[0]

def tld_of(domain: str) -> str:
    d = dom_root(domain)
    if not d or "." not in d:
        return ""
    parts = d.split(".")
    return (".".join(parts[-2:]) if parts[-2] in ("co", "com", "org", "net", "gov", "ac")
            and len(parts) >= 3 else parts[-1])

# ccTLDs that are decisively non-US
FOREIGN_TLD = re.compile(r"^(ca|de|uk|co\.uk|fr|it|es|nl|be|ch|at|se|no|dk|fi|pl|cz|pt|gr|ie|"
                         r"au|com\.au|nz|jp|cn|com\.cn|in|co\.in|br|com\.br|mx|com\.mx|ar|cl|co|pe|"
                         r"za|co\.za|ru|tr|il|co\.il|ae|sa|sg|com\.sg|my|th|id|co\.id|ph|vn|kr|tw|hk|"
                         r"ro|hu|bg|hr|si|sk|lt|lv|ee|ua|is|lu|mt|cy|ma|ng|ke|eg)$", re.I)

EMP_RANGE = re.compile(r"employs\s+([0-9][0-9,]*)\s*(?:to|-|–)\s*([0-9][0-9,]*)\s*(?:people|employees)", re.I)
EMP_SINGLE = re.compile(r"employs\s+([0-9][0-9,]*)\s*(?:people|employees)", re.I)

def band_of(emp: float) -> str:
    for name, lo, hi in BANDS:
        if emp >= lo and (hi is None or emp <= hi):
            return name
    return "1000+"

def parse_employees(desc: str):
    """Midpoint of the employee band stated in ZoomInfo-style description prose."""
    if not desc:
        return None
    m = EMP_RANGE.search(desc)
    if m:
        lo, hi = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
        return (lo + hi) / 2
    m = EMP_SINGLE.search(desc)
    return float(m.group(1).replace(",", "")) if m else None

# ---------------------------------------------------------------- statistics
def wls(xs, ys, ws):
    """Weighted least squares y = a + b*x. Returns (a, b, weighted_r2)."""
    Sw = sum(ws); Swx = sum(w*x for w,x in zip(ws,xs)); Swy = sum(w*y for w,y in zip(ws,ys))
    Swxx = sum(w*x*x for w,x in zip(ws,xs)); Swxy = sum(w*x*y for w,x,y in zip(ws,xs,ys))
    den = Sw*Swxx - Swx*Swx
    b = (Sw*Swxy - Swx*Swy)/den if den else 0.0
    a = (Swy - b*Swx)/Sw if Sw else 0.0
    ybar = Swy/Sw if Sw else 0.0
    ssr = sum(w*(y-(a+b*x))**2 for w,x,y in zip(ws,xs,ys))
    sst = sum(w*(y-ybar)**2 for w,y in zip(ws,ys))
    return a, b, (1 - ssr/sst if sst else 0.0)

def poisson_ci(n: int):
    """Byar approximation to the exact Poisson 95% CI — avoids a scipy dependency."""
    if n <= 0:
        return [0.0, 3.0]
    lo = n*(1 - 1/(9*n) - 1.96/(3*math.sqrt(n)))**3
    hi = (n+1)*(1 - 1/(9*(n+1)) + 1.96/(3*math.sqrt(n+1)))**3
    return [round(max(0.0, lo), 2), round(hi, 2)]

# ---------------------------------------------------------------- load
def load_victims():
    recs = []
    for f in sorted(RAW.glob("sector_*.json")):
        try:
            arr = json.loads(f.read_text(encoding="utf-8").lstrip("﻿"))
        except Exception:
            continue
        if isinstance(arr, list):
            recs.extend(arr)
    return recs


def main() -> int:
    dry = "--dry-run" in sys.argv
    cw = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    sectors = cw["sectors"]
    sec_by_tag = {s["ransomware_live_sector"].strip().lower(): s for s in sectors}

    exposure = json.loads(EXPOSURE.read_text(encoding="utf-8"))
    firms = {}        # (industry_id, band) -> firms
    exp_total = {}    # industry_id -> doc
    us_total = None   # unduplicated US firms by band — the size-fit population
    for d in exposure:
        if d["kind"] == "exposure":
            firms[(d["industry_id"], d["size_band"])] = d["firms"]
        elif d["kind"] == "exposure_us_total":
            us_total = d
        else:
            exp_total[d["industry_id"]] = d
    if us_total is None:
        print("missing exposure_us_total doc — re-run: python scripts/fetch_exposure.py")
        return 1

    calib, calib_doc = {}, None
    r_default, r_low, r_high = DEFAULT_R, R_LOW, R_HIGH
    if CALIBRATION.exists():
        calib_doc = json.loads(CALIBRATION.read_text(encoding="utf-8"))
        calib = dict(calib_doc.get("multipliers") or {})
        sched = calib_doc.get("published_schedule") or {}
        r_low = (sched.get("low") or {}).get("value", R_LOW)
        r_default = (sched.get("central") or {}).get("value", DEFAULT_R)
        r_high = (sched.get("high") or {}).get("value", R_HIGH)
        print(f"calibration: schedule low {r_low} / central {r_default} / high {r_high} "
              f"(derived); per-sector measured for {len(calib)} of {len(sectors)} sectors")
    else:
        print(f"no calibration file — falling back to assumed R = {DEFAULT_R} for all sectors "
              f"(run scripts/estimate_underreporting.py to measure it)")

    pdi = process_dependence()
    victims = load_victims()
    print(f"loaded {len(victims):,} victim records; process-dependence index derived for "
          f"{len(pdi)} sectors\n")

    # ---------- country imputation priors (measured on known-country records) ----
    known = [v for v in victims if (v.get("country") or "").strip()]
    us_overall = sum(1 for v in known if v["country"] == "US") / len(known)
    by_sec = defaultdict(lambda: [0, 0])
    by_tld = defaultdict(lambda: [0, 0])
    for v in known:
        sk = (v.get("activity") or "").strip().lower()
        by_sec[sk][0] += 1; by_sec[sk][1] += 1 if v["country"] == "US" else 0
        t = tld_of(v.get("domain", ""))
        if t:
            by_tld[t][0] += 1; by_tld[t][1] += 1 if v["country"] == "US" else 0
    p_sec = {k: (n_us/n) for k, (n, n_us) in by_sec.items() if n >= 20}
    p_tld = {k: (n_us/n) for k, (n, n_us) in by_tld.items() if n >= 30}

    def us_weight(v):
        """1.0 measured US; 0.0 measured non-US or foreign ccTLD; else estimated."""
        c = (v.get("country") or "").strip()
        if c:
            return 1.0 if c == "US" else 0.0
        t = tld_of(v.get("domain", ""))
        if t and FOREIGN_TLD.match(t):
            return 0.0                                    # Stage 1, measured
        sk = (v.get("activity") or "").strip().lower()
        ps = p_sec.get(sk, us_overall)
        if t and t in p_tld:                              # Stage 2, estimated
            return max(0.0, min(1.0, p_tld[t] * ps / us_overall))
        return ps

    # ---------- numerator: 2025, deduped to distinct firms --------------------
    def year_of(v):
        d = (v.get("attackdate") or "")[:4]
        return int(d) if d.isdigit() else None

    seen = defaultdict(set)
    obs = defaultdict(float); adj = defaultdict(float); obs_n = defaultdict(int)
    n_year = n_year_unknown = n_dropped_cctld = 0
    for v in victims:
        if year_of(v) != EXPOSURE_YEAR:
            continue
        n_year += 1
        if not (v.get("country") or "").strip():
            n_year_unknown += 1
            if (t := tld_of(v.get("domain", ""))) and FOREIGN_TLD.match(t):
                n_dropped_cctld += 1
        sk = (v.get("activity") or "").strip().lower()
        s = sec_by_tag.get(sk)
        if not s:
            continue
        key = dom_root(v.get("domain", "")) or norm_name(v.get("victim", ""))
        if not key or key in seen[sk]:
            continue                                      # distinct firms, not listings
        seen[sk].add(key)
        iid = s["industry_id"]
        w = us_weight(v)
        if (v.get("country") or "").strip() == "US":
            obs[iid] += 1; obs_n[iid] += 1
        adj[iid] += w

    # ---------- size model: fit on the pooled labelled sample ----------------
    lab = defaultdict(int)
    n_lab = n_lab_us = 0
    for v in victims:
        e = parse_employees(v.get("description", ""))
        if e is None:
            continue
        n_lab += 1
        if (v.get("country") or "") == "US":
            n_lab_us += 1
        lab[band_of(e)] += 1

    # Fit against the UNDUPLICATED US band distribution, not the sector sums: a
    # multi-sector firm appears once in the population a victim is drawn from, but
    # once per sector in the sector sums, and since large firms span more sectors
    # the summed distribution over-weights them and flattens the curve (b 0.85->0.75).
    firm_tot = {b: us_total["firms_by_band"][b] for b, _, _ in BANDS}
    all_firms = us_total["firms_total"]; all_lab = sum(lab.values())

    rel, fit_rows = {}, []
    for b, _, _ in BANDS:
        fs = firm_tot[b]/all_firms if all_firms else 0
        vs = lab[b]/all_lab if all_lab else 0
        r = (vs/fs) if fs > 0 else 0.0
        rel[b] = r
        if r > 0 and lab[b] > 0:
            fit_rows.append((math.log(BAND_MID[b]), math.log(r), lab[b]))
    a, bexp, r2 = wls([x for x,_,_ in fit_rows], [y for _,y,_ in fit_rows], [w for _,_,w in fit_rows])

    # Broken power law: fitted below the breakpoint, flat above it. The raw fit
    # over-predicts the top band ~4x (implied SMB:large of 60x is not credible);
    # very large firms are plausibly less likely to be *listed* given an attack.
    def rr(band):
        if band == SATURATION_BAND:
            return math.exp(a + bexp*math.log(BAND_MID["500-999"]))
        return math.exp(a + bexp*math.log(BAND_MID[band]))

    # Denominator caveats that apply to specific sectors, resolved in the method doc.
    DENOM_ASSUMPTIONS = {
        "agriculture-forestry-fishing-and-food-production": ["A-VINTAGE", "A-AGRI-DENOM"],
        "public-administration-government": ["A-PUBLIC-UNIT"],
    }

    # ---------- assemble ------------------------------------------------------
    docs, marg_rows = [], []
    for s in sectors:
        iid, tag = s["industry_id"], s["ransomware_live_sector"]
        den_assume = DENOM_ASSUMPTIONS.get(iid, ["A-VINTAGE"])
        et = exp_total[iid]
        R = calib.get(tag, r_default)
        # "estimated" only where this sector's own R was measured by capture-recapture;
        # every other sector carries a value transported from the measurable strata.
        R_basis = "estimated" if tag in calib else "assumed"
        o, ad = obs[iid], adj[iid]
        den_tot = et["firms"]

        if et["band_split_available"]:
            wsum = sum(firms[(iid, b)] * rr(b) for b, _, _ in BANDS)
            for band, lo, hi in BANDS:
                f = firms[(iid, band)]
                share = (f * rr(band) / wsum) if wsum else 0
                v_obs, v_adj = o*share, ad*share
                per10k = lambda x: round(10000.0*x/f, 2) if f else None
                docs.append({
                    "_id": f"freq:{EXPOSURE_YEAR}:{iid}:{band}", "kind": "cell",
                    "exposure_year": EXPOSURE_YEAR, "industry": s["industry"], "industry_id": iid,
                    "ransomware_live_sector": tag,
                    "size_dimension": "employees", "size_band": band,
                    "size_band_min": lo, "size_band_max": hi,
                    "numerator": {
                        "observed": {"value": round(v_obs, 2), "basis": "estimated",
                                     "assumption_ids": ["A-SIZE-ALLOC", "A-NO-SIZE-INDUSTRY-INTERACTION"]},
                        "country_adjusted": {"value": round(v_adj, 2), "basis": "estimated",
                                             "assumption_ids": ["A-COUNTRY-MAR", "A-SIZE-ALLOC"]},
                        "under_reporting_adjusted": {"value": round(v_adj*R, 2), "basis": "estimated",
                                                     "assumption_ids": ["A-UNDERREPORT"]},
                    },
                    "denominator": {"firms": f, "basis": "measured", "unit": et["denominator_unit"],
                                    "assumption_ids": den_assume,
                                    "source": et["source"], "vintage": 2022,
                                    "naics": et["naics"], "naics_exclude": et["naics_exclude"],
                                    "crosswalk_confidence": et["crosswalk_confidence"]},
                    "rate": {"observed_per_10k": per10k(v_obs), "central_per_10k": per10k(v_adj*R),
                             "low_per_10k": per10k(v_adj*r_low), "high_per_10k": per10k(v_adj*r_high),
                             "relative_size_rate": round(rr(band), 3), "basis": "derived"},
                    "segmentation": {"sensitive_information": et.get("sensitive_information"),
                                     "regulatory_regimes": et.get("regulatory_regimes", []),
                                     "process_dependence_index": (pdi.get(tag) or {}).get("index")},
                    "provenance": {"generated_at": NOW, "method_doc_id": f"freq:method:{EXPOSURE_YEAR}",
                                   "script": "build_frequency.py"},
                })

        per10k = lambda x: round(10000.0*x/den_tot, 2) if den_tot else None
        docs.append({
            "_id": f"freq:{EXPOSURE_YEAR}:{iid}:ALL", "kind": "industry_marginal",
            "exposure_year": EXPOSURE_YEAR, "industry": s["industry"], "industry_id": iid,
            "ransomware_live_sector": tag,
            "numerator": {
                "observed": {"value": obs_n[iid], "basis": "measured",
                             "note": "country==US, 2025, distinct firms"},
                "country_adjusted": {"value": round(ad, 1), "basis": "estimated",
                                     "assumption_ids": ["A-COUNTRY-MAR"]},
                "under_reporting_adjusted": {"value": round(ad*R, 1), "basis": "estimated",
                                             "assumption_ids": ["A-UNDERREPORT"]},
            },
            "under_reporting_multiplier": {"value": R, "basis": R_basis,
                                           "assumption_ids": ["A-UNDERREPORT"]},
            "denominator": {"firms": den_tot, "basis": "measured", "unit": et["denominator_unit"],
                            "assumption_ids": den_assume,
                            "source": et["source"], "vintage": 2022, "naics": et["naics"],
                            "naics_exclude": et["naics_exclude"],
                            "crosswalk_confidence": et["crosswalk_confidence"],
                            "band_split_available": et["band_split_available"]},
            "rate": {"observed_per_10k": per10k(o), "central_per_10k": per10k(ad*R),
                     "low_per_10k": per10k(ad*r_low), "high_per_10k": per10k(ad*r_high),
                     "observed_poisson_ci_95_count": poisson_ci(obs_n[iid]), "basis": "derived"},
            "segmentation": {"sensitive_information": et.get("sensitive_information"),
                             "regulatory_regimes": et.get("regulatory_regimes", []),
                             "process_dependence": pdi.get(tag),
                             "process_dependence_index": (pdi.get(tag) or {}).get("index")},
            "provenance": {"generated_at": NOW, "method_doc_id": f"freq:method:{EXPOSURE_YEAR}",
                           "script": "build_frequency.py"},
        })
        marg_rows.append((tag, obs_n[iid], round(ad,1), den_tot, per10k(o), per10k(ad*R),
                          et["crosswalk_confidence"], et["denominator_unit"], ad*R))

    for band, lo, hi in BANDS:
        docs.append({
            "_id": f"freq:{EXPOSURE_YEAR}:size:{band}", "kind": "size_marginal",
            "exposure_year": EXPOSURE_YEAR, "size_dimension": "employees", "size_band": band,
            "size_band_min": lo, "size_band_max": hi,
            "firms": firm_tot[band], "firms_basis": "unduplicated US total (SUSB NAICS '--')",
            "firm_share": round(firm_tot[band]/all_firms, 5) if all_firms else None,
            "labelled_victims": lab[band],
            "victim_share": round(lab[band]/all_lab, 5) if all_lab else None,
            "relative_rate_empirical": round(rel[band], 3),
            "relative_rate_fitted": round(rr(band), 3),
            "labelled_poisson_ci_95": poisson_ci(lab[band]),
            "basis": "estimated", "assumption_ids": ["A-SIZE-SAMPLE", "A-ZOOMINFO-BIAS"] +
                                                    (["A-SATURATION"] if band == SATURATION_BAND else []),
            "provenance": {"generated_at": NOW, "method_doc_id": f"freq:method:{EXPOSURE_YEAR}"},
        })

    # The robustness claim: the country adjustment and the under-reporting multiplier
    # both move the LEVEL. If the industry ORDERING survives them, the ordering is a
    # product of the data rather than of the assumptions. Check it, do not assert it.
    rank_obs = [r[0] for r in sorted(marg_rows, key=lambda r: -(r[4] or 0))]
    rank_cen = [r[0] for r in sorted(marg_rows, key=lambda r: -(r[5] or 0))]

    method = {
        "_id": f"freq:method:{EXPOSURE_YEAR}", "kind": "method", "generated_at": NOW,
        "exposure_year": EXPOSURE_YEAR, "scope": "United States",
        "what_is_measured": ("Probability that a US firm is LISTED ON A RANSOMWARE LEAK SITE in a "
                             "calendar year. Not attack-occurrence frequency: 65% of records have "
                             "attackdate == discovered, so the date is largely the posting date."),
        "size_model": {"form": "broken_power_law", "intercept_log": round(a, 4),
                       "elasticity_b": round(bexp, 4), "weighted_r2": round(r2, 4),
                       "breakpoint_band": SATURATION_BAND, "b_above_breakpoint": 0.0,
                       "n_labelled": n_lab, "n_labelled_us": n_lab_us,
                       "fit_population": ("unduplicated US firms by band (SUSB NAICS '--', 6,395,635) "
                                          "- NOT the sum over sectors, which double-counts multi-sector "
                                          "firms, over-weights large firms and flattens b to 0.75"),
                       "interpretation": f"attack rate scales ~ employees^{bexp:.2f} below 1000 employees"},
        "under_reporting": {
            "central": r_default, "low": r_low, "high": r_high,
            "schedule_basis": "derived" if calib_doc else "assumed",
            "measured_by_sector": calib or None,
            "sectors_measured": sorted(calib) or None,
            "sectors_transported": sorted(s["ransomware_live_sector"] for s in sectors
                                          if s["ransomware_live_sector"] not in calib),
            "method": ("Chapman capture-recapture against the independent Comparitech list, with a "
                       "dependence sweep bounded by the observed overlap rate M/B. See "
                       "scripts/estimate_underreporting.py and the frequency:calibration doc."),
            "calibration_doc_id": (calib_doc or {}).get("_id"),
            "dependence_sweep": (calib_doc or {}).get("dependence_model"),
        },
        "country_imputation": {"p_us_overall": round(us_overall, 4),
                               "records_in_exposure_year": n_year,
                               "country_unknown_in_exposure_year": n_year_unknown,
                               "country_unknown_pct_exposure_year": round(100*n_year_unknown/n_year, 2) if n_year else None,
                               "dropped_foreign_cctld": n_dropped_cctld,
                               "note": ("Missing country is 24.9% CORPUS-WIDE but concentrated in 2021-2023 "
                                        "(2021: 86.4%, 2022: 77.5%, 2023: 54.4%, 2024: 2.9%, 2025: 3.1%). "
                                        "In the 2025 exposure year the numerator is ~97% measured, so the "
                                        "country adjustment is a minor correction (+3.5%), not a major one. "
                                        "This is a further reason to restrict rates to 2025."),
                               "p_us_by_sector": {k: round(v, 4) for k, v in sorted(p_sec.items())},
                               "p_us_by_tld": {k: round(v, 4) for k, v in
                                               sorted(p_tld.items(), key=lambda x: -x[1])[:15]}},
        "excluded": {"years_excluded": "<=2024 and 2026",
                     "reason": ("2025 is the only year with complete 12-month coverage across all 14 "
                                "sectors; earlier years have missing sector-months (e.g. Construction "
                                "29 US victims in 2024 vs 303 in 2025 — a tagging/backfill artifact). "
                                "2026 is right-censored mid-July in this snapshot.")},
        "assumptions": [
            {"id": "A-COUNTRY-MAR", "statement": "Country is missing-at-random given sector and TLD.",
             "basis": "assumed", "bias_direction": "unknown",
             "derivation": f"Only {n_year_unknown} of {n_year} exposure-year records ({100*n_year_unknown/n_year:.1f}%) "
                           "lack country — missingness is concentrated in 2021-2023, not 2025. Foreign ccTLDs "
                           "excluded outright (measured); the remainder weighted by "
                           "P(US|TLD) * P(US|sector) / P(US|overall).",
             "sensitivity": "LOW IMPACT: the adjustment moves the numerator ~+3.5%. observed_per_10k and "
                            "central_per_10k differ by a near-constant factor, so the ranking is unaffected."},
            {"id": "A-UNDERREPORT",
             "statement": f"Leak-site listings undercount true incidents by R (central {r_default}x).",
             "basis": "estimated" if calib_doc else "assumed", "bias_direction": "understates",
             "derivation": ("Chapman capture-recapture against the Comparitech list. The lists are "
                            "positively dependent (Comparitech partly sources from leak sites), which "
                            "inflates the overlap M and so DEFLATES N_hat — naive Lincoln-Petersen is "
                            "therefore a hard LOWER BOUND. The bias is bounded above as well: a sourced "
                            "record necessarily matches, so leak-sourced records are at most M/B of "
                            "Comparitech (15-21% by stratum). Sweeping the sourced fraction over that "
                            "bounded range yields the published schedule."
                            if calib_doc else
                            "Not yet measured — run scripts/estimate_underreporting.py."),
             "sensitivity": f"low={r_low}, central={r_default}, high={r_high} published on every cell. "
                            "This is MULTIPLICATIVE on the level and cancels out of the ranking, which "
                            "is why the ranking is the more defensible product."},
            {"id": "A-SIZE-SAMPLE", "statement": "Size distribution is estimated from the pooled GLOBAL labelled sample.",
             "basis": "estimated", "bias_direction": "unknown",
             "derivation": f"Only {n_lab} records carry employee prose and just {n_lab_us} are US — too few for "
                           "US-only, industry-stratified estimation.",
             "sensitivity": "Assumes size distribution transports from global to US."},
            {"id": "A-NO-SIZE-INDUSTRY-INTERACTION", "statement": "The size curve is identical across industries.",
             "basis": "assumed", "bias_direction": "unknown",
             "derivation": "Sample supports one pooled curve, not 14. Certainly false in reality — a "
                           "manufacturing SMB and a consumer-services SMB get the same multiplier.",
             "sensitivity": "Band-level cells are far weaker than industry marginals. Prefer the marginals."},
            {"id": "A-ZOOMINFO-BIAS", "statement": "Firmographic labels under-represent the smallest firms.",
             "basis": "assumed", "bias_direction": "overstates",
             "derivation": "Labels exist only where a ZoomInfo-style profile was pasted; such profiles are "
                           "sparse below ~5-10 employees. The 1-4 band (63% of all US firms) rests on a "
                           "handful of records, so its measured relative rate is biased DOWN and the "
                           "fitted elasticity is therefore biased UP (too steep).",
             "sensitivity": "The single weakest link in the size dimension."},
            {"id": "A-SATURATION", "statement": "The size curve is flat above 1,000 employees.",
             "basis": "assumed", "bias_direction": "unknown",
             "derivation": "The raw power law over-predicts the top band ~4x (implied SMB:large of 60x is "
                           "not credible). Very large firms are plausibly LESS likely to be listed given "
                           "an attack (quiet payment, negotiated delisting, counsel-managed disclosure).",
             "sensitivity": "Pin independently with SEC 8-K Item 1.05, the one stratum with a known "
                            "denominator and a mandatory numerator."},
            {"id": "A-AGRI-DENOM", "statement": "Agriculture uses employer firms, not the ~1.9M USDA farm count.",
             "basis": "assumed", "bias_direction": "overstates",
             "derivation": "USDA NASS counts every farm including those with no payroll and no IT estate. "
                           "Employer firms are the realistic target population; using 1.9M would dilute ~30x.",
             "sensitivity": "Swap denominator_source to nass_2022 to test."},
            {"id": "A-PUBLIC-UNIT", "statement": "Public Sector is measured per GOVERNMENT, not per firm.",
             "basis": "measured", "bias_direction": "n/a",
             "derivation": "NAICS 92 is absent from SUSB entirely. Census of Governments gives 90,887 units. "
                           "A county is one unit but runs many separately attackable agencies.",
             "sensitivity": "Never compare this rate to firm-based rates without the unit label."},
            {"id": "A-SIZE-ALLOC", "statement": "Victims are allocated across bands as firms_in_band x relative_rate(band).",
             "basis": "estimated", "bias_direction": "unknown",
             "derivation": "Industry totals are measured; the split across bands is modelled.",
             "sensitivity": "Band cells inherit all size-model uncertainty."},
            {"id": "A-VINTAGE", "statement": "2022 denominators against 2025 numerators.",
             "basis": "assumed", "bias_direction": "overstates",
             "derivation": "US employer-firm counts move 1-2%/yr; ~3-5% cumulative, negligible beside a 7x "
                           "under-reporting multiplier.",
             "sensitivity": "Roll forward with Census BDS if ever material."},
        ],
        "process_dependence_index": {
            "definition": "share of an industry's hazard + exposure categories classified into the "
                          "'OT & Operational Disruption' or 'Business Interruption' families",
            "source": "data/industries.json taxonomy (categories AND subcategories pooled, 60-145 "
                      "entries per industry), classified with the FAMILIES regexes mirrored from "
                      "scripts/export_mongo.js",
            "basis": "derived",
            "by_sector": {k: v["index"] for k, v in sorted(pdi.items(), key=lambda x: -x[1]["index"])},
            "USE": "Interpretive segmentation only. It is a SEVERITY-flavoured construct (how badly "
                   "a stoppage hurts), deliberately NOT multiplied into frequency, because no "
                   "evidence base supports a coefficient and conflating the two would double-count.",
        },
        "sources": [
            {"name": "Census SUSB 2022 (firm counts by NAICS x employment size)", "role": "denominator",
             "url": "https://www2.census.gov/programs-surveys/susb/tables/2022/us_state_naics_detailedsizes_2022.txt",
             "machine_readable": True},
            {"name": "Census of Governments 2022", "role": "denominator",
             "url": "https://www.census.gov/programs-surveys/cog/data/tables.html", "machine_readable": False},
            {"name": "NCES CCD / IPEDS", "role": "denominator", "url": "https://nces.ed.gov/ccd/",
             "machine_readable": False},
            {"name": "ransomware.live leak-site victims", "role": "numerator",
             "url": "https://api.ransomware.live/", "machine_readable": True},
            {"name": "Comparitech ransomware trackers", "role": "calibration",
             "url": "https://www.comparitech.com/ransomware-attack-map/", "machine_readable": True},
            {"name": "NAIC Cybersecurity Insurance Market Report (1.14% all-cyber claim frequency, 2024)",
             "role": "validation",
             "url": "https://content.naic.org/sites/default/files/inline-files/2025_Cybersecurity_Insurance%20Report.pdf",
             "machine_readable": False},
        ],
        "known_limitations": [
            "The under-reporting multiplier is a LOWER BOUND (positive list dependence).",
            "Size x industry interaction is assumed away (65 US labelled records).",
            "ZoomInfo coverage bias makes the fitted elasticity too steep.",
            "'Business Services' spans 5 unrelated NAICS sectors; its rate is near-meaningless.",
            "Public Sector denominator is governments, a different unit from firms.",
            "Measures leak-site LISTING frequency, not attack-occurrence frequency.",
            "One usable year (2025) — no trend, no credibility weighting.",
            "Do NOT use the DBIR 88%/39% SMB split as a size skew: it is a conditional composition "
            "(given a breach, what share was ransomware), not an attack rate.",
        ],
    }
    method["ranking_stability"] = {
        "observed_order": rank_obs, "central_order": rank_cen,
        "identical": rank_obs == rank_cen,
        "positions_held": sum(1 for i, t in enumerate(rank_obs) if rank_cen[i] == t),
        "of": len(rank_obs),
        "note": ("The country and under-reporting adjustments move the LEVEL. Where the ordering "
                 "survives them, it is a product of the data and not of the assumptions. The "
                 "ordering is the robust deliverable; the absolute level carries roughly 2x "
                 "multiplicative uncertainty from the under-reporting multiplier alone."),
        "basis": "derived",
    }
    docs.append(method)

    # ---------- report --------------------------------------------------------
    print(f"size model: log(rel_rate) = {a:.3f} + {bexp:.3f}*log(employees)   "
          f"weighted R2={r2:.3f}  n={n_lab} (US {n_lab_us})")
    print(f"  -> rate scales ~ employees^{bexp:.2f} below 1,000; flat above (A-SATURATION)\n")
    print(f"{'industry':34} {'obs':>5} {'adj':>7} {'denominator':>12} {'obs/10k':>8} {'central/10k':>11}  conf    unit")
    for tag, o, ad, den, r_o, r_c, conf, unit, _ in sorted(marg_rows, key=lambda r: -(r[5] or 0)):
        print(f"{tag:34} {o:>5} {ad:>7.1f} {den:>12,} {r_o if r_o is not None else 0:>8.2f} "
              f"{r_c if r_c is not None else 0:>11.2f}  {conf:<7} {unit}")
    tot_o = sum(r[1] for r in marg_rows); tot_a = sum(r[2] for r in marg_rows)
    tot_d = sum(r[3] for r in marg_rows); tot_ur = sum(r[8] for r in marg_rows)
    print(f"\n{'ALL':34} {tot_o:>5} {tot_a:>7.1f} {tot_d:>12,} {10000*tot_o/tot_d:>8.2f} "
          f"{10000*tot_ur/tot_d:>11.2f}")
    print(f"  all-industry central rate = {100*tot_ur/tot_d:.3f}%/yr  "
          f"(low {100*tot_a*r_low/tot_d:.3f}% / high {100*tot_a*r_high/tot_d:.3f}%)")
    print("  sanity: NAIC reports 1.14% all-cyber claim frequency (2024). Ransomware is a subset "
          "of all-cyber, so landing below it is correct.")
    if not 0.2 <= 100*tot_ur/tot_d <= 0.6:
        print("  WARNING: central rate outside the expected 0.2-0.6%/yr band")
    if rank_obs == rank_cen:
        print(f"\nranking stability: IDENTICAL across the observed and central numerators "
              f"({len(rank_obs)}/{len(rank_obs)} positions) — the ordering does not depend on "
              f"the country or under-reporting adjustments.")
    else:
        moved = [(t, rank_obs.index(t) + 1, rank_cen.index(t) + 1)
                 for t in rank_obs if rank_obs.index(t) != rank_cen.index(t)]
        print(f"\nranking stability: {len(rank_obs)-len(moved)}/{len(rank_obs)} positions held. "
              f"moved: " + ", ".join(f"{t} {a}->{b}" for t, a, b in moved))

    if pdi:
        print("\nprocess-dependence index (interpretive segmentation, NOT a rate multiplier):")
        ranked = sorted(pdi.items(), key=lambda x: -x[1]["index"])
        for tag, v in ranked:
            bar = "#" * round(v["index"] * 40)
            print(f"  {tag:34} {v['index']:.3f}  {v['categories_operational']:>2}/{v['categories_total']:<2} {bar}")

    print(f"\ndocs: {sum(1 for d in docs if d['kind']=='cell')} cell, "
          f"{sum(1 for d in docs if d['kind']=='industry_marginal')} industry_marginal, "
          f"{sum(1 for d in docs if d['kind']=='size_marginal')} size_marginal, 1 method")

    if dry:
        print("\n[dry-run] nothing written.")
        return 0
    OUT.write_text(json.dumps(docs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {len(docs)} docs -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
