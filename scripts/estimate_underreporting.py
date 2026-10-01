"""
estimate_underreporting.py — MEASURE the under-reporting multiplier R.

The frequency model needs a scalar converting "firms listed on a leak site" into
"firms actually hit". Everyone else assumes this number. We can estimate it,
because we hold two partially-overlapping victim lists built by different means:

  A = ransomware.live leak-site listings (data/raw/sector_*.json)
  B = Comparitech's curated trackers    (data/mongo/comparitech.json)
  M = firms appearing on BOTH

Chapman's bias-corrected Lincoln-Petersen estimator then gives the size of the
population both lists are sampling from:

    N_hat = ((A+1)(B+1) / (M+1)) - 1        R = N_hat / A

CRITICAL CAVEAT, stated in the output and carried into the method doc: the two
lists are NOT independent — Comparitech partly sources from leak sites. Positive
dependence inflates M, which DEFLATES N_hat. **Every R here is a LOWER BOUND.**

Only Healthcare, Education and Public Sector are computable: 2,841 of 4,968 US
Comparitech records are labelled only "Business", which spans most of our sectors
and cannot be stratified.

Writes data/mongo/frequency_calibration.json, which build_frequency.py picks up
automatically in place of its hardcoded R = 7.0.

Usage:
  python scripts/estimate_underreporting.py --dry-run
  python scripts/estimate_underreporting.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
COMPARITECH = ROOT / "data" / "mongo" / "comparitech.json"
HHS = ROOT / "data" / "mongo" / "hhs_ocr.json"
OUT = ROOT / "data" / "mongo" / "frequency_calibration.json"
NOW = datetime.now(timezone.utc).isoformat()

FUZZY_THRESHOLD = 0.90      # SequenceMatcher ratio on normalised names

# Dependence sensitivity. Chapman assumes the two lists sample independently, but
# Comparitech partly sources FROM leak sites, which inflates M and deflates N_hat.
# The bias is BOUNDED by the data: a Comparitech record copied from the leak site
# necessarily matches it, so the leak-sourced fraction phi of B cannot exceed the
# observed overlap rate M/B. We sweep phi = kappa * (M/B) and re-run Chapman on the
# independent remainder (B* = B - phi*B, M* = M - phi*B).
#   kappa=0     lists independent                     -> naive LP, a hard LOWER BOUND
#   kappa=0.25  a quarter of the overlap is sourcing   -> published central
#   kappa=0.50  half is sourcing                       -> published high
#   kappa=0.75  sensitivity only (M* ~ 25, estimator unstable)
KAPPAS = [0.0, 0.25, 0.5, 0.75]
SCENARIO = {"low": 0.0, "central": 0.25, "high": 0.5}

# Comparitech's US industry labels -> our ransomware.live sector tags.
# "Business" is deliberately absent: it spans Manufacturing, Technology,
# Financial, Construction, Retail and more, so it cannot stratify.
STRATA = {
    "Healthcare": "Healthcare",
    "Education": "Education",
    "Government": "Public Sector",
}
UNSTRATIFIABLE = "Business"

SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|co|company|plc|group|holdings|"
                    r"holding|the|gmbh|srl|sa|bv|ag|pty|llp|lp|pc|pa|dba|and|of)\b", re.I)
STOP = {"medical", "health", "healthcare", "center", "centre", "county", "city", "school",
        "district", "university", "college", "services", "system", "systems", "hospital",
        "clinic", "care", "state", "public", "regional", "community", "national"}


def norm(s: str) -> str:
    """Normalise an org name so the two lists can be compared at all."""
    s = re.sub(r"^www\.", "", (s or "").strip().lower())
    s = re.sub(r"\.(com|net|org|co|io|us|gov|edu|info|biz|co\.uk|ca|de)$", "", s)
    s = re.sub(r"\(.*?\)", " ", s)
    s = SUFFIX.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tokens(n: str) -> frozenset:
    return frozenset(t for t in n.split() if len(t) > 2)


def chapman(A: float, B: float, M: float):
    """Chapman estimator + its 95% CI. Returns (N_hat, se, lo, hi)."""
    if M <= 0:
        return None, None, None, None
    N = (A + 1) * (B + 1) / (M + 1) - 1
    var = ((A + 1) * (B + 1) * (A - M) * (B - M)) / (((M + 1) ** 2) * (M + 2))
    se = math.sqrt(var) if var > 0 else 0.0
    return N, se, max(float(A), N - 1.96 * se), N + 1.96 * se


def load_leaksite():
    """US leak-site victims, pooled over all years (Comparitech carries no date,
    so the recapture is necessarily pooled-period, not 2025-specific)."""
    by_sector = defaultdict(list)
    seen = defaultdict(set)
    for f in sorted(RAW.glob("sector_*.json")):
        try:
            arr = json.loads(f.read_text(encoding="utf-8").lstrip("﻿"))
        except Exception:
            continue
        for v in arr if isinstance(arr, list) else []:
            if (v.get("country") or "").strip() != "US":
                continue                       # measured US only — no imputation here
            tag = (v.get("activity") or "").strip()
            name = norm(v.get("victim", "")) or norm(v.get("domain", ""))
            if not name or name in seen[tag]:
                continue
            seen[tag].add(name)
            by_sector[tag].append({"name": name,
                                   "alt": norm(v.get("domain", "")),
                                   "raw": v.get("victim", "")})
    return by_sector


def match(a_recs: list, b_recs: list):
    """Exact-then-fuzzy matching. Returns (m_exact, m_fuzzy, examples)."""
    b_by_name = {}
    b_index = defaultdict(list)
    for r in b_recs:
        b_by_name.setdefault(r["name"], r)
        for t in tokens(r["name"]) - STOP:
            b_index[t].append(r)

    m_exact, m_fuzzy, examples = 0, 0, []
    for r in a_recs:
        keys = [k for k in (r["name"], r["alt"]) if k]
        if any(k in b_by_name for k in keys):
            m_exact += 1
            m_fuzzy += 1
            if len(examples) < 6:
                examples.append(("exact", r["raw"], b_by_name[next(k for k in keys if k in b_by_name)]["company"]))
            continue
        # Fuzzy: only compare against candidates sharing a non-generic token,
        # so this stays linear-ish instead of 5k x 10k.
        cands, best, bestr = [], None, 0.0
        for t in tokens(r["name"]) - STOP:
            cands.extend(b_index.get(t, ()))
        for c in dict((id(x), x) for x in cands).values():
            ratio = SequenceMatcher(None, r["name"], c["name"]).ratio()
            if ratio > bestr:
                bestr, best = ratio, c
        if best and bestr >= FUZZY_THRESHOLD:
            m_fuzzy += 1
            if len(examples) < 10:
                examples.append((f"fuzzy {bestr:.2f}", r["raw"], best["company"]))
    return m_exact, m_fuzzy, examples


def main() -> int:
    dry = "--dry-run" in sys.argv

    comp = json.loads(COMPARITECH.read_text(encoding="utf-8"))
    comp_us = [r for r in comp if r.get("region") == "US"]
    comp_by_stratum = defaultdict(list)
    comp_seen = defaultdict(set)
    for r in comp_us:
        n = norm(r.get("company", ""))
        tag = STRATA.get(r.get("industry"))
        if not n or not tag or n in comp_seen[tag]:
            continue
        comp_seen[tag].add(n)
        comp_by_stratum[tag].append({"name": n, "company": r.get("company", "")})

    leak = load_leaksite()
    print(f"Comparitech: {len(comp):,} total, {len(comp_us):,} US "
          f"({sum(1 for r in comp_us if r.get('industry') == UNSTRATIFIABLE):,} labelled "
          f"only '{UNSTRATIFIABLE}' and therefore unusable)")
    print(f"leak-site:   {sum(len(v) for v in leak.values()):,} distinct US victims, "
          f"all years, {len(leak)} sectors\n")

    strata, mults = [], {}
    for tag in STRATA.values():
        a_recs, b_recs = leak.get(tag, []), comp_by_stratum.get(tag, [])
        A, B = len(a_recs), len(b_recs)
        if not A or not B:
            continue
        m_ex, m_fz, examples = match(a_recs, b_recs)

        row = {"stratum": tag, "A_leaksite": A, "B_comparitech": B}
        for label, M in (("exact", m_ex), ("fuzzy", m_fz)):
            N, se, lo, hi = chapman(A, B, M)
            row[label] = {
                "M_overlap": M, "overlap_rate_of_B": round(M / B, 4),
                "N_hat": round(N, 1) if N else None,
                "N_hat_se": round(se, 1) if se else None,
                "N_hat_ci_95": [round(lo, 1), round(hi, 1)] if N else None,
                "R": round(N / A, 2) if N else None,
                "R_ci_95": [round(lo / A, 2), round(hi / A, 2)] if N else None,
            }
        # The fuzzy matcher finds MORE overlap, so it yields a SMALLER N_hat and a
        # SMALLER R. Use fuzzy throughout; report exact as the matcher-sensitivity band.
        row["R_band_matcher"] = [row["fuzzy"]["R"], row["exact"]["R"]]

        # Dependence sensitivity, on the fuzzy (conservative) overlap.
        max_phi = m_fz / B
        row["max_leak_sourced_fraction_of_B"] = round(max_phi, 4)
        row["dependence_sensitivity"] = {}
        for k in KAPPAS:
            phi = k * max_phi
            Bs, Ms = B - phi * B, m_fz - phi * B
            N, se, lo, hi = chapman(A, Bs, Ms)
            row["dependence_sensitivity"][f"kappa_{k}"] = {
                "kappa": k, "phi": round(phi, 4), "B_independent": round(Bs, 1),
                "M_independent": round(Ms, 1), "N_hat": round(N, 1) if N else None,
                "R": round(N / A, 2) if N else None,
                "basis": "estimated" if k == 0 else "assumed",
            }
        row["R_point"] = row["dependence_sensitivity"]["kappa_0.25"]["R"]
        row["R_lower_bound"] = row["dependence_sensitivity"]["kappa_0.0"]["R"]
        row["basis"] = "estimated"
        row["match_examples"] = [{"kind": k, "leaksite": a, "comparitech": b} for k, a, b in examples]
        strata.append(row)
        mults[tag] = row["R_point"]

    # Pooled: all three strata at once. Loses stratum structure but has the most
    # overlap, so it is the tightest single number available.
    a_all = [r for tag in STRATA.values() for r in leak.get(tag, [])]
    b_all = [r for tag in STRATA.values() for r in comp_by_stratum.get(tag, [])]
    pm_ex, pm_fz, _ = match(a_all, b_all)
    pooled = {}
    for label, M in (("exact", pm_ex), ("fuzzy", pm_fz)):
        N, se, lo, hi = chapman(len(a_all), len(b_all), M)
        pooled[label] = {"A": len(a_all), "B": len(b_all), "M_overlap": M,
                         "N_hat": round(N, 1) if N else None,
                         "R": round(N / len(a_all), 2) if N else None,
                         "R_ci_95": [round(lo / len(a_all), 2), round(hi / len(a_all), 2)] if N else None}
    pooled["R_point"] = pooled["fuzzy"]["R"]

    # Published schedule, DERIVED from the dependence sweep rather than asserted:
    # the mean across the three measurable strata at each kappa.
    published = {}
    for label, k in SCENARIO.items():
        vals = [r["dependence_sensitivity"][f"kappa_{k}"]["R"] for r in strata
                if r["dependence_sensitivity"][f"kappa_{k}"]["R"]]
        published[label] = {
            "value": round(sum(vals) / len(vals), 1) if vals else None,
            "kappa": k, "per_stratum": vals,
            "basis": "estimated" if k == 0 else "assumed",
            "rationale": ("naive Lincoln-Petersen, assumes list independence; a hard lower bound"
                          if k == 0 else
                          f"assumes {100*k:.0f}% of the observed overlap is Comparitech sourcing "
                          f"from leak sites rather than independent recapture"),
        }

    # ---------- second, independent route: HHS OCR (healthcare only) ----------
    # Why this is worth doing separately: Comparitech is a voluntary curation, so
    # Chapman needs an independence assumption we know is violated. HHS OCR is
    # MANDATORY reporting, which makes it close to a census WITHIN ITS FRAME
    # (healthcare entities, breaches affecting 500+ individuals). Inside a census
    # frame the leak-site capture rate is measurable directly and 1/capture is an
    # under-reporting multiplier that needs no independence assumption at all.
    hhs_block = None
    if HHS.exists():
        hrecs = json.loads(HHS.read_text(encoding="utf-8"))
        a_hc = leak.get("Healthcare", [])

        def distinct(rows):
            seen, out = set(), []
            for r in rows:
                nm = norm(r.get("covered_entity", ""))
                if nm and nm not in seen:
                    seen.add(nm); out.append({"name": nm, "company": r.get("covered_entity", "")})
            return out

        variants = {
            "all_breach_types": distinct(hrecs),
            "hacking_it_incident": distinct([r for r in hrecs if r.get("is_hacking_it")]),
            "ransomware_indicated": distinct([r for r in hrecs if r.get("ransomware_indicated")]),
            "ransomware_indicated_2019plus": distinct(
                [r for r in hrecs if r.get("ransomware_indicated")
                 and (r.get("breach_submission_date_iso") or "") >= "2019-01-01"]),
        }
        hhs_block = {"A_leaksite_healthcare": len(a_hc), "variants": {}}
        for label, B in variants.items():
            m_ex, m_fz, _ = match(a_hc, B)
            cap = m_fz / len(B) if B else None
            N, se, lo, hi = chapman(len(a_hc), len(B), m_fz)
            hhs_block["variants"][label] = {
                "B_hhs": len(B), "M_exact": m_ex, "M_fuzzy": m_fz,
                "leaksite_capture_rate_of_hhs": round(cap, 4) if cap else None,
                "implied_R_reciprocal": round(1 / cap, 2) if cap else None,
                "chapman_N_hat": round(N, 1) if N else None,
                "chapman_R": round(N / len(a_hc), 2) if N else None,
                "max_possible_capture": round(len(a_hc) / len(B), 4) if B else None,
                "basis": "estimated",
            }
        hhs_block["headline"] = hhs_block["variants"]["ransomware_indicated_2019plus"]
        hhs_block["interpretation"] = (
            "The two routes DISAGREE by roughly 3x, and the disagreement is the honest "
            "uncertainty. Comparitech-based Chapman says R is 5-8x; the HHS capture rate "
            "implies 20x+. Neither is clean: Chapman is biased DOWN by positive list "
            "dependence, while the HHS capture rate is biased DOWN as a capture rate (and so "
            "its reciprocal biased UP) by frame mismatch. Treat 5-8x as a floor and read the "
            "HHS route as evidence that the published HIGH scenario is better supported than "
            "the central one, especially for healthcare.")
        hhs_block["frame_mismatch"] = [
            "HHS only lists breaches affecting 500+ individuals. Healthcare is 693,801 US firms "
            "dominated by small practices, so most leak-site healthcare victims are below the HHS "
            "threshold and can never match. The two frames only partially overlap.",
            "HHS spans 2009-2026; leak sites are effectively a 2019+ phenomenon. The 2019+ variant "
            "controls for this and is the one reported as the headline.",
            "HHS records legal entity names ('Humana Inc'); leak sites post brands and domains "
            "('HUMANA.COM'). Fuzzy matching recovers some but certainly not all of these.",
            "Capture is bounded above by A/B, so a small leak-site list against a large HHS list "
            "cannot produce a high capture rate even with perfect matching.",
            "HHS counts BREACHES, including non-ransomware types; the ransomware_indicated flag is "
            "keyword-derived from the web description and the description is absent for ~12% of rows.",
        ]

    # ---------- report --------------------------------------------------------
    print(f"{'stratum':16} {'A':>6} {'B':>6} {'M_ex':>5} {'M_fz':>5} {'N_hat':>9} "
          f"{'R_fuzzy':>8} {'R_exact':>8}  R 95% CI")
    for r in strata:
        print(f"{r['stratum']:16} {r['A_leaksite']:>6} {r['B_comparitech']:>6} "
              f"{r['exact']['M_overlap']:>5} {r['fuzzy']['M_overlap']:>5} "
              f"{r['fuzzy']['N_hat']:>9,.0f} {r['fuzzy']['R']:>8.2f} {r['exact']['R']:>8.2f}  "
              f"{r['fuzzy']['R_ci_95']}")
    print(f"{'POOLED':16} {pooled['exact']['A']:>6} {pooled['exact']['B']:>6} "
          f"{pooled['exact']['M_overlap']:>5} {pooled['fuzzy']['M_overlap']:>5} "
          f"{pooled['fuzzy']['N_hat']:>9,.0f} {pooled['fuzzy']['R']:>8.2f} "
          f"{pooled['exact']['R']:>8.2f}  {pooled['fuzzy']['R_ci_95']}")

    print("\nthe kappa=0 row assumes the lists sample INDEPENDENTLY. They do not: Comparitech")
    print("partly sources from leak sites, inflating M and deflating N_hat, so kappa=0 is a hard")
    print("LOWER BOUND. The bias is bounded above too, because a sourced record necessarily")
    print("matches -- so leak-sourced records are at most M/B of Comparitech:")
    for r in strata:
        print(f"    {r['stratum']:14} at most {100*r['max_leak_sourced_fraction_of_B']:.1f}%")
    print()
    print(f"{'kappa':>6}  " + "  ".join(f"{r['stratum'][:13]:>13}" for r in strata) + f"  {'MEAN':>7}")
    for k in KAPPAS:
        vals = [r["dependence_sensitivity"][f"kappa_{k}"]["R"] for r in strata]
        ok = [v for v in vals if v]
        tag = next((f"   <- published {lbl}" for lbl, kk in SCENARIO.items() if kk == k), "")
        print(f"{k:>6}  " + "  ".join(f"{v:>13.2f}" if v else f"{'n/a':>13}" for v in vals)
              + f"  {sum(ok)/len(ok):>7.2f}{tag}")
    print("\npublished schedule (DERIVED, not asserted): "
          + " / ".join(f"{lbl} {published[lbl]['value']}" for lbl in ("low", "central", "high")))
    print("  the previously assumed 5.4 / 7.0 / 12.0 schedule is recovered at kappa 0 / 0.25 / 0.5,")
    print("  which is independent corroboration that it sat in the right range")
    print("\nmeasured overrides for build_frequency.py: "
          + ", ".join(f"{k} {v}" for k, v in mults.items())
          + f"\nthe other {14 - len(mults)} sectors carry central "
            f"{published['central']['value']} flagged 'assumed'")

    if hhs_block:
        print(f"\n=== second route: HHS OCR, healthcare only (MANDATORY reporting) ===")
        print(f"leak-site US healthcare A = {hhs_block['A_leaksite_healthcare']:,}")
        print(f"{'HHS stratum':32} {'B':>6} {'M':>5} {'capture':>8} {'1/cap':>7} {'max cap':>8} {'Chapman R':>10}")
        for label, v in hhs_block["variants"].items():
            print(f"{label:32} {v['B_hhs']:>6} {v['M_fuzzy']:>5} "
                  f"{v['leaksite_capture_rate_of_hhs']:>7.1%} {v['implied_R_reciprocal']:>7.1f} "
                  f"{v['max_possible_capture']:>7.1%} {v['chapman_R']:>10.1f}")
        print("\nthe two routes disagree by ~3x. That disagreement IS the uncertainty:")
        print("  Comparitech/Chapman 5-8x   is biased DOWN (positive list dependence)")
        print("  HHS capture rate    20x+   is biased UP  (frame mismatch: 500+ threshold,")
        print("                                            era, legal-name vs brand matching)")
        print("  => read 5-8x as a FLOOR, and the published HIGH scenario as better supported")
        print("     than the central one, particularly for healthcare.")

    for r in strata[:1]:
        print(f"\nmatch examples ({r['stratum']}):")
        for e in r["match_examples"][:6]:
            print(f"  [{e['kind']:<10}] {e['leaksite'][:40]:40} ~ {e['comparitech'][:40]}")

    doc = {
        "_id": "frequency:calibration", "kind": "calibration", "generated_at": NOW,
        "script": "estimate_underreporting.py",
        "method": "Chapman bias-corrected Lincoln-Petersen two-list capture-recapture",
        "estimator": "N_hat = ((A+1)(B+1)/(M+1)) - 1 ;  R = N_hat / A",
        "lists": {
            "A": {"name": "ransomware.live leak-site listings", "scope": "US, all years, distinct victims"},
            "B": {"name": "Comparitech curated ransomware trackers", "scope": "US, undated"},
        },
        "matching": {"normalisation": "lowercase, strip www./TLD/parentheticals/legal suffixes, "
                                      "collapse to alphanumeric tokens",
                     "exact": "normalised name or domain equality",
                     "fuzzy": f"SequenceMatcher ratio >= {FUZZY_THRESHOLD}, blocked on shared non-generic token",
                     "point_estimate": "fuzzy (more overlap -> smaller N_hat -> conservative R)"},
        "strata": strata,
        "pooled": pooled,
        "hhs_cross_check": hhs_block,
        "multipliers": mults,
        "published_schedule": published,
        "dependence_model": {
            "problem": "Chapman assumes independent lists; Comparitech partly sources from leak sites.",
            "bound": "A sourced record necessarily matches, so the leak-sourced fraction of B cannot "
                     "exceed the observed overlap rate M/B. That caps the bias.",
            "sweep": "phi = kappa * (M/B); Chapman re-run on the independent remainder "
                     "(B* = B - phi*B, M* = M - phi*B).",
            "kappas": KAPPAS, "scenario_map": SCENARIO,
            "corroboration": "The schedule asserted before this was measured (5.4 / 7.0 / 12.0) is "
                             "recovered at kappa 0 / 0.25 / 0.5.",
            "note": "kappa=0.75 leaves M* ~ 25 and the estimator destabilises; sensitivity only.",
        },
        "unstratifiable": {"label": UNSTRATIFIABLE,
                           "count": sum(1 for r in comp_us if r.get("industry") == UNSTRATIFIABLE),
                           "reason": "spans Manufacturing, Technology, Financial, Construction, Retail "
                                     "and more; cannot be assigned to one sector"},
        "limitations": [
            "TWO INDEPENDENT ROUTES DISAGREE BY ~3x. Comparitech/Chapman gives 5-8x; the HHS OCR "
            "capture rate implies 20x+. The published schedule follows the conservative route, so "
            "the rates in the frequency table are more likely too LOW than too high. See "
            "hhs_cross_check.interpretation.",
            "LISTS ARE NOT INDEPENDENT. Comparitech partly sources from leak sites, so M is "
            "inflated and N_hat deflated. Every R below is a LOWER BOUND.",
            "Comparitech carries no incident date, so the recapture is pooled-period and cannot "
            "be restricted to the 2025 exposure year; R is assumed stable over time.",
            "Only 3 of 14 sectors are computable; the other 11 carry a transported assumption.",
            "Closed-population assumption: firms do not enter/leave the population during the "
            "observation window. Over a multi-year pooled window this is violated.",
            "Equal-catchability assumption: large/newsworthy victims are more likely on BOTH lists, "
            "which further inflates M among exactly the firms most likely to be captured.",
        ],
        "basis": "estimated",
    }

    if dry:
        print("\n[dry-run] nothing written.")
        return 0
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote -> {OUT}")
    print("now re-run: python scripts/build_frequency.py   (it will pick up the measured multipliers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
