"""
make_figures.py — publication figures for the frequency model and benchmarks.

Six figures, one message each, written to figures/ as PNG (2x for slides).
Style is deliberately minimal: one hue family (Carolina blue on navy), no
chart junk, the point of the figure stated in its title and the number that
carries it labelled directly on the mark rather than read off an axis.

Reads  data/mongo/frequency.json, benchmarks.json, frequency_calibration.json
Writes figures/fig1..fig6 .png

Usage: python scripts/make_figures.py
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)

L = lambda f: json.loads(io.open(ROOT / "data" / "mongo" / f, encoding="utf-8-sig").read())
freq = L("frequency.json")
bench = L("benchmarks.json")
cal = L("frequency_calibration.json")
marg = sorted((d for d in freq if d["kind"] == "industry_marginal"),
              key=lambda d: d["rate"]["central_per_10k"])
sizes = [d for d in freq if d["kind"] == "size_marginal"]
method = next(d for d in freq if d["kind"] == "method")
byyear = next(d for d in bench if d["kind"] == "victims_by_year")["years"]
dbir = next(d for d in bench if d["kind"] == "dbir_benchmark")

NAVY, CAROLINA, SKY, GREY, OX = "#13294B", "#4B9CD3", "#A8CCE4", "#8A939B", "#9E3B33"
plt.rcParams.update({
    "font.family": "Arial", "font.size": 10.5,
    "axes.edgecolor": "#C9CDD2", "axes.linewidth": 0.8,
    "axes.titlesize": 12.5, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
    "axes.labelcolor": "#3A4149", "text.color": "#3A4149",
    "xtick.color": "#6C737A", "ytick.color": "#3A4149",
    "figure.facecolor": "white", "axes.facecolor": "white",
    "svg.fonttype": "none",
})


def strip(ax, keep_x=False):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if not keep_x:
        ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(length=0)


def save(fig, name, note):
    # Below the canvas (negative figure y): bbox_inches="tight" expands to include
    # it, so the note never collides with an axis label however short the figure.
    fig.text(0.015, -0.045, note, fontsize=7.6, color=GREY, va="top", wrap=True)
    fig.savefig(FIG / f"{name}.png", dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {name}.png")


SHORT = {"Agriculture and Food Production": "Agriculture & Food",
         "Hospitality and Tourism": "Hospitality", "Transportation/Logistics": "Transportation",
         "Financial Services": "Financial Svcs", "Business Services": "Business Svcs",
         "Consumer Services": "Consumer Svcs", "Telecommunication": "Telecom"}
nm = lambda t: SHORT.get(t, t)

# ---------------------------------------------------------------- fig 1: rates
fig, ax = plt.subplots(figsize=(8.6, 5.4))
tags = [nm(d["ransomware_live_sector"]) for d in marg]
obs = [d["rate"]["observed_per_10k"] for d in marg]
cen = [d["rate"]["central_per_10k"] for d in marg]
lo = [d["rate"]["low_per_10k"] for d in marg]
hi = [d["rate"]["high_per_10k"] for d in marg]
y = range(len(marg))
ax.barh(y, cen, height=0.62, color=CAROLINA, zorder=3)
ax.hlines(y, lo, hi, color=NAVY, lw=1.4, zorder=4)
for i, d in enumerate(marg):
    ax.text(hi[i] + 6, i, f"{cen[i]:.0f}", va="center", fontsize=9.3,
            color=NAVY, fontweight="bold")
    unit = " (per government)" if d["denominator"]["unit"] == "governments" else ""
    if unit:
        ax.text(2, i, unit.strip(" ()"), va="center", ha="left", fontsize=7.4, color="white")
ax.set_yticks(list(y), tags)
ax.set_xlabel("expected victims per 10,000 firms per year — central estimate, 2025 US")
ax.set_title("Ransomware frequency varies 28× across industries")
ax.set_xlim(0, max(hi) * 1.1)
strip(ax)
ax.xaxis.grid(True, color="#ECEEF0", zorder=0)
save(fig, "fig1_rate_by_industry",
     "Bars: central rate (leak-site victims ÷ Census SUSB firm counts × under-reporting 7.4×). "
     "Whiskers: under-reporting scenario band (5.8–10.6×), not a confidence interval. "
     "Public Sector is per government, not per firm.")

# ---------------------------------------------------------------- fig 2: size
fig, ax = plt.subplots(figsize=(8.6, 4.6))
bands = [d["size_band"] for d in sizes]
fsh = [100 * d["firm_share"] for d in sizes]
vsh = [100 * d["victim_share"] for d in sizes]
x = range(len(bands))
w = 0.38
ax.bar([i - w / 2 for i in x], fsh, width=w, color=SKY, label="share of US firms", zorder=3)
ax.bar([i + w / 2 for i in x], vsh, width=w, color=NAVY, label="share of victims (size-labelled)", zorder=3)
for i in x:
    ax.text(i - w / 2, fsh[i] + 1.2, f"{fsh[i]:.0f}%", ha="center", fontsize=8.6, color="#5B7FA6")
    ax.text(i + w / 2, vsh[i] + 1.2, f"{vsh[i]:.0f}%", ha="center", fontsize=8.6,
            color=NAVY, fontweight="bold")
ax.set_xticks(list(x), bands)
ax.set_xlabel("employees")
ax.set_title("63% of US firms are tiny — and almost never the victim")
ax.legend(frameon=False, loc="upper right")
ax.set_ylim(0, 72)
strip(ax, keep_x=True)
ax.yaxis.set_visible(False)
b = method["size_model"]["elasticity_b"]
ax.text(3.5, 50, f"fitted: rate ~ employees^{b:.2f}\n(weighted R² = "
        f"{method['size_model']['weighted_r2']:.2f}, n = {method['size_model']['n_labelled']})",
        fontsize=9.5, color=OX, ha="center")
save(fig, "fig2_size",
     "Firm shares: Census SUSB 2022, unduplicated US totals. Victim shares: the 227 leak-site "
     "records carrying an employee label. DBIR 2026 independently finds ~96% of ransomware "
     "victims are SMBs (<1,000 staff); this sample: 95.6%.")

# ---------------------------------------------------------------- fig 3: under-reporting routes
fig, ax = plt.subplots(figsize=(8.6, 3.6))
rows = []
for s in cal["strata"]:
    ds = s["dependence_sensitivity"]
    rows.append((f"capture–recapture · {s['stratum']}",
                 ds["kappa_0.0"]["R"], ds["kappa_0.5"]["R"], ds["kappa_0.25"]["R"]))
h = cal["hhs_cross_check"]["headline"]
yy = range(len(rows) + 1)
for i, (lab, lo_, hi_, pt) in enumerate(rows):
    ax.hlines(i, lo_, hi_, color=SKY, lw=7, zorder=2)
    ax.plot(pt, i, "o", color=NAVY, ms=8, zorder=4)
    ax.text(hi_ + 0.35, i, f"{pt:.1f}×", va="center", color=NAVY, fontweight="bold", fontsize=9.5)
i = len(rows)
ax.plot(h["implied_R_reciprocal"], i, "D", color=OX, ms=8, zorder=4)
ax.text(h["implied_R_reciprocal"] + 0.35, i, f"{h['implied_R_reciprocal']:.0f}×",
        va="center", color=OX, fontweight="bold", fontsize=9.5)
labels = [r[0] for r in rows] + ["mandatory HHS registry · capture 4.6%"]
ax.set_yticks(list(yy), labels)
sch = cal["published_schedule"]
ax.axvline(sch["central"]["value"], color=GREY, lw=1, ls="--", zorder=1)
ax.text(sch["central"]["value"] + 0.25, -0.62, f"published central {sch['central']['value']}×",
        ha="left", fontsize=8.6, color=GREY, va="center")
ax.set_ylim(-0.95, len(rows) + 0.45)
ax.set_xlim(0, 25)
ax.set_xlabel("under-reporting multiplier R  (true incidents per leak-site listing)")
ax.set_title("Leak sites undercount 6–22×, measured two independent ways")
strip(ax)
ax.xaxis.grid(True, color="#ECEEF0", zorder=0)
save(fig, "fig3_underreporting",
     "Bands: Chapman capture–recapture vs the independent Comparitech list, swept over the "
     "bounded list-dependence range (dot = published per-sector value). Diamond: reciprocal of "
     "leak-site capture of HHS's mandatory 500+ healthcare registry. Published schedule "
     "5.8 / 7.4 / 10.6× follows the conservative route.")

# ---------------------------------------------------------------- fig 4: by year
yr = [y for y in byyear if 2020 <= y["year"] <= 2026]
fig, ax = plt.subplots(figsize=(8.6, 4.4))
xs = [y["year"] for y in yr]
cols = [CAROLINA if y["year"] == 2025 else (SKY if y["country_known_pct"] > 90 else "#D4DCE2")
        for y in yr]
ax.bar(xs, [y["distinct_orgs"] for y in yr], color=cols, zorder=3)
for y in yr:
    ax.text(y["year"], y["distinct_orgs"] + 120, f"{y['distinct_orgs']:,}",
            ha="center", fontsize=8.8,
            color=NAVY if y["year"] == 2025 else GREY,
            fontweight="bold" if y["year"] == 2025 else "normal")
    if y["distinct_orgs"] > 900:          # skip the % label on bars too short to hold it
        ax.text(y["year"], 260, f"{y['country_known_pct']:.0f}%", ha="center", fontsize=8,
                color="white" if y["year"] == 2025 else
                      ("#5B7FA6" if y["country_known_pct"] > 90 else GREY))
ax.text(2025, -820, "rate year", ha="center", fontsize=8.6, color=CAROLINA, fontweight="bold")
ax.text(2026, -820, "partial", ha="center", fontsize=8.6, color=GREY)
ax.set_title("Why 2025: the only complete year with usable country data")
ax.set_xticks(xs)
strip(ax, keep_x=True)
ax.yaxis.set_visible(False)
ax.set_ylim(0, 8200)
save(fig, "fig4_by_year",
     "Distinct victim organisations per year, global, with the share carrying a confirmed "
     "country printed at the base. Grey years lack country data (14–46% known, 2021–2023); "
     "2026 is right-censored mid-year. 2025: 6,973 distinct orgs, 96.9% with country.")

# ---------------------------------------------------------------- fig 5: DBIR mix
fig, ax = plt.subplots(figsize=(6.4, 6.0))
rows = dbir["industry_mix"]["rows"]
mx = max(max(r["leak_site_share"], r["dbir_share"]) for r in rows) * 108
ax.plot([0, mx], [0, mx], color="#D4DCE2", lw=1, zorder=1)
OFFS = {"Healthcare": (-0.4, 0.75), "Consumer Svcs": (0.45, -0.75),
        "Construction": (0.45, 0.35), "Transportation": (0.45, 0.45),
        "Education": (0.5, -0.85), "Agriculture & Food": (-0.3, -1.15),
        "Energy": (0.45, -0.4), "Hospitality": (0.45, 0.55),
        "Manufacturing": (0.5, 0.55), "Technology + Telecom": (0.5, 0.55),
        "Business Svcs": (-0.4, 0.8), "Financial Svcs": (0.5, 0.45),
        "Public Sector": (0.5, -0.95)}
for r in rows:
    x_, y_ = 100 * r["dbir_share"], 100 * r["leak_site_share"]
    gap = abs(x_ - y_) > 5
    ax.plot(x_, y_, "o", ms=7, color=OX if gap else CAROLINA, zorder=3)
    short = nm(r["sector"].replace(" + Telecommunication", " + Telecom"))
    dx, dy = OFFS.get(short, (0.5, 0.5))
    ha = "right" if dx < 0 else "left"
    ax.annotate(short, (x_, y_), xytext=(x_ + dx, y_ + dy), fontsize=8.2, ha=ha,
                color=NAVY if gap else GREY)
ax.set_xlabel("share of DBIR 2026 incidents (Table 3, p.77)")
ax.set_ylabel("share of leak-site victims (2025)")
ax.set_title("Two lenses, one mix — gaps follow reporting duty")
ax.text(0.97, 0.04, f"Spearman ρ = {dbir['industry_mix']['spearman_rank_correlation']}",
        transform=ax.transAxes, ha="right", fontsize=9.5, color=NAVY, fontweight="bold")
strip(ax, keep_x=True)
ax.spines["left"].set_visible(True)
ax.xaxis.grid(True, color="#ECEEF0", zorder=0)
ax.yaxis.grid(True, color="#ECEEF0", zorder=0)
save(fig, "fig5_dbir_mix",
     "Red = gap over 5pp. Public Sector and Financial Services sit far below the diagonal: "
     "heavier in DBIR, which receives the mandatory and law-enforcement reporting that "
     "criminal leak sites never see.")

# ---------------------------------------------------------------- fig 6: ransom ladder
fig, ax = plt.subplots(figsize=(8.6, 3.6))
steps = [("paid\n(DBIR 2026 median)", 139875),
         ("demanded, tracked\n(Comparitech, n=623)", 428163),
         ("in the news\n(researched set, n=73)", 8000000)]
xs = range(len(steps))
ax.bar(xs, [v for _, v in steps], color=[SKY, CAROLINA, NAVY], width=0.5, zorder=3)
for i, (lab, v) in enumerate(steps):
    ax.text(i, v * 1.25, f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.0f}k",
            ha="center", fontsize=11, fontweight="bold", color=NAVY)
ax.set_yscale("log")
ax.set_ylim(5e4, 4e7)
ax.set_xticks(list(xs), [s[0] for s in steps])
ax.yaxis.set_visible(False)
strip(ax, keep_x=True)
ax.set_title("The ransom ladder: each list selects for bigger incidents")
save(fig, "fig6_ransom_ladder",
     "Medians, log scale — roughly an order of magnitude per rung. Quoting a 'typical ransom' "
     "without naming the rung misleads by 10×. DBIR 2026 also reports 69% of victims did not pay.")

print(f"\n6 figures -> {FIG}")
