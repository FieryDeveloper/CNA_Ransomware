"""
fetch_exposure.py — the EXPOSURE BASE (denominator) for the frequency model.

Everything else in this project counts attacks (numerators). To turn counts into
a rate you need to know how many firms exist. That comes from the Census Bureau's
Statistics of U.S. Businesses (SUSB), which publishes firm counts by NAICS and by
employment size of firm — the two dimensions the model needs.

Note for anyone reading the brief: BEA does NOT publish firm counts (it publishes
value added / gross output). SUSB does, and needs no API key.

Reads  data/naics_crosswalk.json
Writes data/mongo/frequency_exposure.json

Usage:
  python scripts/fetch_exposure.py --dry-run     # print the table, write nothing
  python scripts/fetch_exposure.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CROSSWALK = ROOT / "data" / "naics_crosswalk.json"
CACHE = ROOT / "data" / "raw" / "susb_2022_detailedsizes.txt"
OUT = ROOT / "data" / "mongo" / "frequency_exposure.json"

SUSB_URL = ("https://www2.census.gov/programs-surveys/susb/tables/2022/"
            "us_state_naics_detailedsizes_2022.txt")
SUSB_US_TOTAL_FIRMS = 6395635   # NAICS '--', ENTRSIZE 01; used as a sanity reference

# SUSB publishes 23 size classes plus 3 rollups. Map them onto the 8 model bands.
# ENTRSIZE codes are the numeric prefix of ENTRSIZEDSCR ("04:10-14" -> "04").
# Rollups 01 (Total), 06 (<20), 19 (<500) are EXCLUDED or every firm is counted twice.
BANDS = [
    ("1-4",      1,     4,    ["02"]),
    ("5-9",      5,     9,    ["03"]),
    ("10-19",    10,    19,   ["04", "05"]),
    ("20-49",    20,    49,   ["07", "08", "09", "10", "11"]),
    ("50-99",    50,    99,   ["12", "13"]),
    ("100-499",  100,   499,  ["14", "15", "16", "17", "18"]),
    ("500-999",  500,   999,  ["20", "21"]),
    ("1000+",    1000,  None, ["22", "23", "24", "25", "26"]),
]
ROLLUP_CODES = {"01", "06", "19"}


def fetch_susb() -> str:
    if CACHE.exists() and CACHE.stat().st_size > 1_000_000:
        print(f"using cached SUSB ({CACHE.stat().st_size/1e6:.1f} MB)")
        return CACHE.read_text(encoding="utf-8", errors="replace")
    print(f"downloading SUSB 2022 ...")
    raw = urlopen(Request(SUSB_URL, headers={"User-Agent": "cna-ransomware-research/1.0"}),
                  timeout=300).read().decode("utf-8", "replace")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(raw, encoding="utf-8")
    print(f"cached -> {CACHE} ({len(raw)/1e6:.1f} MB)")
    return raw


def parse_susb(raw: str) -> dict:
    """{naics: {band_name: {firms, estabs, employees, receipts}}} for the US."""
    out = defaultdict(lambda: defaultdict(lambda: {"firms": 0, "estabs": 0, "employees": 0, "receipts": 0}))
    code_to_band = {c: b[0] for b in BANDS for c in b[3]}
    n = 0
    for r in csv.DictReader(raw.splitlines()):
        if r["STATE"] != "00":
            continue
        ent = (r.get("ENTRSIZEDSCR") or "").strip()[:2]
        if ent in ROLLUP_CODES:
            continue
        band = code_to_band.get(ent)
        if not band:
            continue
        cell = out[r["NAICS"]][band]
        for key, col in (("firms", "FIRM"), ("estabs", "ESTB"), ("employees", "EMPL"), ("receipts", "RCPT")):
            try:
                cell[key] += int(r.get(col) or 0)
            except ValueError:
                pass   # SUSB suppresses some cells; flagged in *_FL_N columns
        n += 1
    print(f"parsed {n:,} US size-class rows across {len(out):,} NAICS codes")
    return out


def validate(sectors: list) -> list[str]:
    """Structural checks. The one rule NOT applied: 'sum of sectors <= US total'.
    SUSB counts a firm in every sector it operates in, so summing all 20 top-level
    sectors gives 6,461,497 against an unduplicated 6,395,635 (1.03% over) — that
    check would fail spuriously. Verified 2026-10-01."""
    errs, assigned = [], {}
    for s in sectors:
        net = set(s.get("naics", [])) - set(s.get("naics_exclude", []))
        for code in net:
            if code in assigned:
                errs.append(f"NAICS {code} assigned to both '{assigned[code]}' and '{s['ransomware_live_sector']}'")
            assigned[code] = s["ransomware_live_sector"]
    return errs


def main() -> int:
    dry = "--dry-run" in sys.argv
    cw = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    sectors = cw["sectors"]

    errs = validate(sectors)
    if errs:
        print("CROSSWALK VALIDATION FAILED:")
        for e in errs:
            print("  !", e)
        return 1
    print(f"crosswalk validated: {len(sectors)} sectors, no NAICS assigned twice\n")

    susb = parse_susb(fetch_susb())

    def agg(codes, excludes):
        """Sum the added codes and subtract the excluded ones, per band."""
        res = {b[0]: {"firms": 0, "estabs": 0, "employees": 0, "receipts": 0} for b in BANDS}
        for sign, group in ((1, codes), (-1, excludes)):
            for code in group:
                for band, vals in susb.get(code, {}).items():
                    for k in res[band]:
                        res[band][k] += sign * vals[k]
        return res

    docs, rows = [], []
    for s in sectors:
        bands = agg(s.get("naics", []), s.get("naics_exclude", []))
        susb_total = sum(b["firms"] for b in bands.values())

        sup = s.get("supplement")
        sup_count = (sup or {}).get("count", 0)
        # Distribute a supplement across bands using this sector's own SUSB shape.
        # Where there is no SUSB base at all (Public Sector), no band split is
        # possible — the sector gets an industry-level denominator only.
        band_split_available = susb_total > 0

        # Allocate the supplement across bands by LARGEST REMAINDER, not by rounding
        # each band independently: independent rounding lost a firm (Education's
        # bands summed to 118,204 against a total of 118,205), which then broke the
        # invariant that band firm counts sum to the industry denominator.
        sup_by_band = {b[0]: 0 for b in BANDS}
        if sup_count and band_split_available:
            exact = {b[0]: sup_count * bands[b[0]]["firms"] / susb_total for b in BANDS}
            sup_by_band = {k: int(v) for k, v in exact.items()}
            short = sup_count - sum(sup_by_band.values())
            for k in sorted(exact, key=lambda k: -(exact[k] - int(exact[k])))[:short]:
                sup_by_band[k] += 1
            assert sum(sup_by_band.values()) == sup_count

        for band_name, lo, hi, _ in BANDS:
            b = bands[band_name]
            firms = b["firms"]
            sup_alloc = sup_by_band[band_name]
            docs.append({
                "_id": f"exposure:2022:{s['industry_id']}:{band_name}",
                "kind": "exposure",
                "denominator_vintage": cw["denominator_vintage"],
                "naics_vintage": cw["naics_vintage"],
                "ransomware_live_sector": s["ransomware_live_sector"],
                "industry": s["industry"], "industry_id": s["industry_id"],
                "size_dimension": "employees",
                "size_band": band_name, "size_band_min": lo, "size_band_max": hi,
                "firms": firms + sup_alloc,
                "firms_susb": firms,
                "firms_supplement": sup_alloc,
                "establishments": b["estabs"], "employees": b["employees"],
                "receipts_usd": b["receipts"],
                "denominator_unit": s["denominator_unit"],
                "band_split_available": band_split_available,
                "naics": s.get("naics", []), "naics_exclude": s.get("naics_exclude", []),
                "crosswalk_confidence": s["confidence"],
                "source": s["denominator_source"],
                "source_url": SUSB_URL if s["denominator_source"].startswith("susb") else (sup or {}).get("source_url"),
                "basis": "measured",
            })
        total = susb_total + sup_count
        docs.append({
            "_id": f"exposure:2022:{s['industry_id']}:ALL",
            "kind": "exposure_total",
            "denominator_vintage": cw["denominator_vintage"],
            "ransomware_live_sector": s["ransomware_live_sector"],
            "industry": s["industry"], "industry_id": s["industry_id"],
            "firms": total, "firms_susb": susb_total, "firms_supplement": sup_count,
            "receipts_usd": sum(b["receipts"] for b in bands.values()),
            "denominator_unit": s["denominator_unit"],
            "band_split_available": band_split_available,
            "naics": s.get("naics", []), "naics_exclude": s.get("naics_exclude", []),
            "crosswalk_confidence": s["confidence"],
            "sensitive_information": s.get("sensitive_information"),
            "regulatory_regimes": s.get("regulatory_regimes", []),
            "supplement": sup, "source": s["denominator_source"], "basis": "measured",
        })
        rows.append((s["ransomware_live_sector"], susb_total, sup_count, total,
                     s["denominator_unit"], s["confidence"], band_split_available))

    # The UNDUPLICATED US distribution by band (SUSB NAICS '--'). Needed separately
    # from the sector sums above: a multi-sector firm is counted once here but once
    # per sector there, and because large firms operate in more sectors the summed
    # distribution over-weights them. The size curve must be fitted against this
    # unduplicated population, since the labelled victim sample is a sample of
    # distinct firms, not of firm-sector pairs.
    us_total = {b[0]: susb.get("--", {}).get(b[0], {}).get("firms", 0) for b in BANDS}
    us_sum = sum(us_total.values())
    if us_sum != SUSB_US_TOTAL_FIRMS:
        print(f"VALIDATION FAILED: NAICS '--' bands sum to {us_sum:,}, expected {SUSB_US_TOTAL_FIRMS:,}")
        return 1
    docs.append({
        "_id": "exposure:2022:US:ALL", "kind": "exposure_us_total",
        "denominator_vintage": cw["denominator_vintage"], "size_dimension": "employees",
        "firms_total": us_sum, "firms_by_band": us_total,
        "share_by_band": {k: round(v / us_sum, 5) for k, v in us_total.items()},
        "receipts_by_band": {b[0]: susb.get("--", {}).get(b[0], {}).get("receipts", 0) for b in BANDS},
        "denominator_unit": "firms", "source": "susb_2022", "source_url": SUSB_URL,
        "basis": "measured",
        "note": ("Unduplicated: NAICS '--' row, not a sum over sectors. Use this as the "
                 "firm-share denominator when fitting the size curve."),
    })

    zero = [r[0] for r in rows if r[3] == 0]
    if zero:
        print(f"VALIDATION FAILED: zero denominator for {zero}")
        return 1

    print(f"{'sector':34} {'SUSB':>10} {'suppl':>8} {'total':>10}  unit          conf    bands")
    for name, su, sp, tot, unit, conf, bs in sorted(rows, key=lambda r: -r[3]):
        print(f"{name:34} {su:>10,} {sp:>8,} {tot:>10,}  {unit:<13} {conf:<7} {'yes' if bs else 'NO'}")
    print(f"\n{'TOTAL':34} {sum(r[1] for r in rows):>10,} {sum(r[2] for r in rows):>8,} {sum(r[3] for r in rows):>10,}")
    print(f"(SUSB unduplicated US total is {SUSB_US_TOTAL_FIRMS:,}; sector sums legitimately "
          f"exceed it because a firm is counted in every sector it operates in)")

    if dry:
        print("\n[dry-run] nothing written.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(docs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {len(docs)} docs -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
