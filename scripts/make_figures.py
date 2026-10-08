"""
make_figures.py — slide-grade figures for the frequency model and benchmarks.

Design rules, learned the hard way:
  - No titles or footnotes inside the PNG. The slide supplies the headline and
    the site's cards supply the sources; baked-in text duplicates both and is
    the first thing that reads as machine-made.
  - Nothing small. Each figure is sized to the exact box it occupies on the
    1920x1080 canvas, and every font size is chosen so no glyph lands under
    ~24 px on screen. px-per-pt = shown_px / (figsize_in * 72).
  - One ink, one accent. Ink #1A2433, muted #8A939B, hairline #D9DEE4, a single
    Carolina Blue #4B9CD3 for the one thing each figure is about. De-emphasised
    series are grey, never a second hue.
  - dpi 260, so every image is ~2.2x its display size: crisp on projectors.

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
byyear = next(d for d in bench if d["kind"] == "victims_by_year")["years"]
dbir = next(d for d in bench if d["kind"] == "dbir_benchmark")

INK, MUTED, HAIR, GREY, ACC = "#1A2433", "#8A939B", "#D9DEE4", "#C7CFD8", "#4B9CD3"
plt.rcParams.update({
    "font.family": "Arial",
    "axes.edgecolor": HAIR, "axes.linewidth": 1.0,
    "axes.labelcolor": MUTED, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": INK,
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def strip(ax, bottom=False, left=False):
    for side, keep in (("top", False), ("right", False), ("bottom", bottom), ("left", left)):
        ax.spines[side].set_visible(keep)
    ax.tick_params(length=0)


def save(fig, name):
    fig.savefig(FIG / f"{name}.png", dpi=260, bbox_inches="tight",
                pad_inches=0.06, facecolor="white")
    plt.close(fig)
    print(f"  {name}.png")


SHORT = {"Agriculture and Food Production": "Agriculture & Food",
         "Hospitality and Tourism": "Hospitality", "Transportation/Logistics": "Transportation",
         "Telecommunication": "Telecommunications"}
nm = lambda t: SHORT.get(t, t)

# ---------------------------------------------------------------- fig 1: rates
# Shown ~1664x660 -> figsize 14x5.55in -> 1.65 px/pt. Base 15pt ~ 25px on screen.
fig, ax = plt.subplots(figsize=(14, 5.55))
tags = [nm(d["ransomware_live_sector"]) for d in marg]
cen = [d["rate"]["central_per_10k"] for d in marg]
lo = [d["rate"]["low_per_10k"] for d in marg]
hi = [d["rate"]["high_per_10k"] for d in marg]
y = range(len(marg))
ax.barh(y, cen, height=0.58, color=ACC, zorder=3)
ax.hlines(y, lo, hi, color=INK, lw=1.6, zorder=4)
# Two right-aligned number columns, clear of the longest whisker (393):
# the rate in ink, the odds in muted. A table, not floating labels.
for i, d in enumerate(marg):
    ax.text(472, i, f"{cen[i]:.0f}", va="center", ha="right", fontsize=17,
            color=INK, fontweight="bold")
    ax.text(588, i, f"1 in {10000/cen[i]:,.0f}", va="center", ha="right",
            fontsize=15, color=MUTED)
ax.set_yticks(list(y), tags, fontsize=15.5)
ax.set_xlabel("expected victims per 10,000 firms per year", fontsize=15, labelpad=10)
ax.set_xlim(0, 592)
ax.set_ylim(-0.6, len(marg) - 0.4)
strip(ax)
ax.xaxis.grid(True, color="#EEF1F4", zorder=0)
ax.set_xticks([0, 100, 200, 300, 400])
ax.tick_params(axis="x", labelsize=14)
save(fig, "fig1_rate_by_industry")

# ---------------------------------------------------------------- fig 2: size
# Shown ~1664x540 -> figsize 14x4.55in.
fig, ax = plt.subplots(figsize=(14, 4.55))
bands = [d["size_band"] for d in sizes]
fsh = [100 * d["firm_share"] for d in sizes]
vsh = [100 * d["victim_share"] for d in sizes]
x = range(len(bands))
w = 0.39
ax.bar([i - w / 2 for i in x], fsh, width=w, color=GREY, zorder=3)
ax.bar([i + w / 2 for i in x], vsh, width=w, color=ACC, zorder=3)
for i in x:
    ax.text(i - w / 2, fsh[i] + 1.6, f"{fsh[i]:.0f}", ha="center", fontsize=15, color=MUTED)
    ax.text(i + w / 2, vsh[i] + 1.6, f"{vsh[i]:.0f}", ha="center", fontsize=16.5,
            color=INK, fontweight="bold")
ax.set_xticks(list(x), bands, fontsize=15.5)
ax.set_xlabel("employees", fontsize=15, labelpad=10)
ax.set_ylim(0, 74)
strip(ax, bottom=True)
ax.yaxis.set_visible(False)
ax.text(0.99, 0.94, "% of US firms", transform=ax.transAxes, ha="right",
        fontsize=15.5, color=MUTED)
ax.text(0.99, 0.83, "% of victims", transform=ax.transAxes, ha="right",
        fontsize=15.5, color=ACC, fontweight="bold")
save(fig, "fig2_size")

# ------------------------------------------------- fig 3: under-reporting
# Shown ~1664x430 -> figsize 14x3.6in.
fig, ax = plt.subplots(figsize=(14, 3.6))
rows = []
for s in cal["strata"]:
    ds = s["dependence_sensitivity"]
    rows.append((s["stratum"], ds["kappa_0.0"]["R"], ds["kappa_0.5"]["R"],
                 ds["kappa_0.25"]["R"]))
h = cal["hhs_cross_check"]["headline"]
for i, (lab, lo_, hi_, pt) in enumerate(rows):
    ax.hlines(i, lo_, hi_, color="#DDE7F0", lw=11, zorder=2)
    ax.plot(pt, i, "o", color=INK, ms=9, zorder=4)
    ax.text(hi_ + 0.4, i, f"{pt:.1f}×", va="center", color=INK,
            fontweight="bold", fontsize=17)
i = len(rows)
ax.plot(h["implied_R_reciprocal"], i, "D", color=ACC, ms=10, zorder=4)
ax.text(h["implied_R_reciprocal"] + 0.4, i, f"{h['implied_R_reciprocal']:.0f}×",
        va="center", color=ACC, fontweight="bold", fontsize=17)
ax.set_yticks(range(len(rows) + 1),
              [f"list overlap · {r[0]}" for r in rows] + ["mandatory HHS registry"],
              fontsize=15.5)
sch = cal["published_schedule"]
ax.axvline(sch["central"]["value"], color=MUTED, lw=1.1, ls=(0, (4, 4)), zorder=1)
ax.text(sch["central"]["value"] + 0.3, -0.72, f"published {sch['central']['value']}×",
        ha="left", va="center", fontsize=14.5, color=MUTED)
ax.set_ylim(-1.0, len(rows) + 0.5)
ax.set_xlim(0, 25)
ax.set_xlabel("true incidents per leak-site listing", fontsize=15, labelpad=10)
ax.set_xticks([0, 5, 10, 15, 20, 25])
ax.tick_params(axis="x", labelsize=14)
strip(ax)
ax.xaxis.grid(True, color="#EEF1F4", zorder=0)
save(fig, "fig3_underreporting")

# ---------------------------------------------------------------- fig 4: years
# Shown ~920x430 -> figsize 10x4.65in -> 1.28 px/pt: 14.5pt ~ 24px min.
yr = [yy for yy in byyear if 2020 <= yy["year"] <= 2026]
fig, ax = plt.subplots(figsize=(10, 4.65))
xs = [yy["year"] for yy in yr]
cols = [ACC if yy["year"] == 2025 else ("#AFC8DC" if yy["country_known_pct"] > 90 else "#DFE4E9")
        for yy in yr]
ax.bar(xs, [yy["distinct_orgs"] for yy in yr], color=cols, zorder=3, width=0.68)
for yy in yr:
    ax.text(yy["year"], yy["distinct_orgs"] + 160, f"{yy['distinct_orgs']:,}",
            ha="center", fontsize=16 if yy["year"] == 2025 else 14.5,
            color=INK if yy["year"] == 2025 else MUTED,
            fontweight="bold" if yy["year"] == 2025 else "normal")
ax.set_xticks(xs, [str(v) for v in xs], fontsize=15)
ax.text(2025, -1060, "rate year", ha="center", fontsize=14.5, color=ACC, fontweight="bold")
ax.text(2026, -1060, "partial", ha="center", fontsize=14.5, color=MUTED)
strip(ax, bottom=True)
ax.yaxis.set_visible(False)
ax.set_ylim(0, 8100)
save(fig, "fig4_by_year")

# ---------------------------------------------------------------- fig 5: DBIR mix
# Shown ~940x620 -> figsize 9.4x6.2in -> 1.39 px/pt: 14pt ~ 24px min.
fig, ax = plt.subplots(figsize=(9.4, 6.2))
rows = dbir["industry_mix"]["rows"]
ax.plot([0, 23], [0, 23], color=HAIR, lw=1.2, zorder=1)
# Every label hand-placed in data units. At presentation type sizes an
# auto-offset scatter always collides; thirteen explicit anchors are cheaper.
LBL = {"Manufacturing": (14.3, 16.45, "left"),
       "Technology + Telecom": (1.0, 16.45, "left"),
       "Business Services": (20.9, 14.55, "right"),
       "Financial Services": (15.1, 6.3, "left"),
       "Public Sector": (14.3, 3.85, "left"),
       "Healthcare": (6.1, 8.8, "left"),
       "Consumer Services": (7.85, 7.7, "left"),
       "Construction": (3.85, 6.85, "left"),
       "Transportation": (0.3, 5.5, "left"),
       "Education": (5.5, 4.3, "left"),
       "Agriculture & Food": (0.35, 3.2, "left"),
       "Hospitality": (4.2, 2.5, "left"),
       "Energy": (2.4, 1.45, "left")}
for r in rows:
    x_, y_ = 100 * r["dbir_share"], 100 * r["leak_site_share"]
    gap = abs(x_ - y_) > 5
    ax.plot(x_, y_, "o", ms=9, color=ACC if gap else "#9FB2C4", zorder=3)
    short = nm(r["sector"])
    if "Technology" in r["sector"]:
        short = "Technology + Telecom"
    lx, ly, ha = LBL[short]
    ax.annotate(short, (x_, y_), xytext=(lx, ly), fontsize=14, ha=ha,
                color=INK if gap else MUTED, zorder=5)
ax.set_xlabel("share of DBIR 2026 incidents", fontsize=15, labelpad=10)
ax.set_ylabel("share of leak-site victims, 2025", fontsize=15, labelpad=10)
ax.set_xlim(-0.5, 24)
ax.set_ylim(-0.5, 24)
ax.set_xticks([0, 5, 10, 15, 20])
ax.set_yticks([0, 5, 10, 15, 20])
ax.tick_params(labelsize=14)
strip(ax, bottom=True, left=True)
save(fig, "fig5_dbir_mix")

# ---------------------------------------------------------------- fig 6: ladder
# Shown ~980x440 -> figsize 10x4.5in.
fig, ax = plt.subplots(figsize=(10, 4.5))
steps = [("paid", "DBIR 2026", 139875),
         ("demanded", "Comparitech, n=623", 428163),
         ("in the news", "researched, n=73", 8000000)]
xs = range(len(steps))
ax.bar(xs, [v for _, _, v in steps], color=["#DFE4E9", "#AFC8DC", ACC],
       width=0.52, zorder=3)
for i, (lab, src, v) in enumerate(steps):
    ax.text(i, v * 1.28, f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}k",
            ha="center", fontsize=21, fontweight="bold", color=INK)
ax.set_xticks(list(xs),
              [lab + "\n" + src for lab, src, _ in steps], fontsize=15, color=MUTED)
ax.tick_params(axis="x", length=0, pad=12)
ax.set_yscale("log")
ax.set_ylim(1e4, 5.2e7)
ax.yaxis.set_visible(False)
for sp in ax.spines.values():
    sp.set_visible(False)
save(fig, "fig6_ransom_ladder")

print(f"\n6 figures -> {FIG}")
