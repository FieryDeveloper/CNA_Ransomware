# What We Built, and What It Says

A plain-language summary of the ransomware risk dataset: what we collected, what it
tells us, and what it cannot tell us. No jargon. Every number here comes from the
data and is checked by a script, not typed from memory.

For the technical detail see [README.md](README.md). For a presentable walkthrough
see [EXPLAINER.md](EXPLAINER.md). To click around the data, open
[explorer.html](explorer.html) or the
[live site](https://fierydeveloper.github.io/CNA_Ransomware/).

---

## The short version

Most ransomware reporting counts attacks. Counting tells you who gets hit **often**.
It cannot tell you how **likely** any one company is to be hit, because a count has
no sense of how many companies there are to begin with.

So we did two things:

1. **Collected 41,644 records** about ransomware attacks from five separate sources.
2. **Divided them by how many companies actually exist** (6.5 million US businesses,
   from the Census Bureau) to turn counts into a probability.

The result: **about 1 in 250 US businesses is hit by ransomware in a year** — but
that average hides a 28-fold difference between the safest and riskiest industries.

---

## 1. What we collected

| Source | Records | What it gives us |
|---|---:|---|
| Ransomware leak sites | **27,108** | Who got attacked, when, in what industry and country |
| Hand-researched incidents | **565** | What it actually cost: money, downtime, records stolen |
| Comparitech trackers | **5,942** | Ransom amounts, extracted from their public maps |
| US government health breach registry | **7,925** | Healthcare breaches 2009–2026, legally required to be reported |
| Cryptocurrency payment tracking | **104** families | Ransom money actually paid, traced on the blockchain: **$336M** |
| **Total** | **41,644** | |

**Why five sources and not one?** Because no single list is complete. Criminals only
publish the victims who refuse to pay. News only covers the big names. Keeping the
lists separate lets us compare them — and the amount they *disagree* tells us how
much they are all missing. That turned out to be the most valuable thing we did
(see section 4).

---

## 2. The main result: how likely is an attack?

For every industry we took the number of US victims in 2025 and divided by the number
of US firms in that industry.

| Industry | Victims (2025) | US firms | Chance per year |
|---|---:|---:|---|
| Telecommunications | 44 | 12,086 | **1 in 36** |
| Energy & Utilities | 71 | 24,113 | **1 in 45** |
| Manufacturing | 581 | 202,208 | **1 in 46** |
| Technology | 419 | 163,176 | **1 in 50** |
| Agriculture & Food | 110 | 59,656 | 1 in 72 |
| Government | 140 | 90,887* | 1 in 76 |
| Education | 174 | 118,205 | 1 in 80 |
| Financial Services | 228 | 244,536 | 1 in 141 |
| Transport & Logistics | 126 | 237,527 | 1 in 240 |
| Healthcare | 365 | 693,801 | 1 in 312 |
| Construction | 295 | 782,487 | 1 in 345 |
| Business Services | 523 | 1,791,252 | 1 in 445 |
| Retail & Consumer | 293 | 1,374,640 | 1 in 608 |
| Hospitality & Tourism | 90 | 723,013 | **1 in 1,035** |
| **All industries** | **3,459** | **6,517,587** | **1 in 249** |

\* Government is counted in *government bodies*, not companies, so it is not directly
comparable to the rows above it.

### The one point to take away

**Counting attacks gives you the wrong answer.** Healthcare had **5 times more
victims than Energy** (365 vs 71). But Energy's **risk is 7 times higher**, because
Healthcare has 694,000 firms and Energy has only 24,000.

By raw count, Healthcare looks like one of the worst-hit industries. By actual risk,
it sits in the bottom half. Construction tells the same story: alarming by count
(295 victims), low risk in practice (1 in 345), because most of those 782,000
construction firms are tiny.

### Bigger companies are hit more

We also found risk rises with company size, in a measurable way: roughly, **risk
scales with employee count to the power of 0.85**. In plain terms, a company ten
times bigger is about seven times more likely to be attacked — not ten times, but
close. This held up well statistically (R² = 0.90).

---

## 3. How bad is it when it happens?

Here the honest answer is: **we can measure how much data gets stolen far better than
we can measure how much money is lost.**

| What we measured | How many cases | Typical (median) | Worst case |
|---|---:|---|---|
| **People's records stolen** | **1,246** | 12,859 people | 9.3 million |
| Ransom demanded | 623 | $430,000 | $200 million |
| Ransom demanded (big incidents only) | 73 | $8 million | $75 million |
| Total cost to the company | **58** | $23 million | $2.9 billion |
| Days of downtime | **~10 usable** | — | — |

**What this means for anyone modelling this:** use records-stolen. We have 1,246
measurements of it and only 58 of total financial cost. Downtime is barely usable —
we have 323 written descriptions of recovery, but only around 10 state a duration
clearly enough to turn into a number.

**One trap worth knowing.** The two ransom figures above disagree by 19× ($430,000
vs $8 million). That is not an error. The 623 figures come from a broad tracker; the
73 come from incidents newsworthy enough to be researched in depth — and newsworthy
means big. Mixing the two would badly overstate the typical ransom.

### The largest cases we have

Biggest reported losses:

| Company | Reported cost | Attacker |
|---|---:|---|
| Change Healthcare | $2.9B | ALPHV/BlackCat, then RansomHub |
| UnitedHealth Group (its parent) | $2.45B | BlackCat |
| MarineMax | $2.39B | Rhysida |
| CDK Global | $1.0B | BlackSuit |
| Irish Health Service (HSE) | $600M | Conti |

Biggest ransom demands: Cencora $75M, TSMC $70M, Kaseya $70M (not paid), Pendragon
$60M, Intrado $60M.

Most money actually collected, traced on the blockchain: **Conti $101.6M**, Cuba
$60.2M, Netwalker $27.5M, BlackSuit $25.0M, BlackCat $21.9M. $336M total across
20,940 individual payments.

---

## 4. The finding we are most confident in, and least comfortable with

**Leak sites only show part of reality.** Everyone in this field knows that. Most
reports pick a number out of the air to correct for it.

We measured it instead. The method is simple enough to explain in a sentence: if two
people independently survey the same crowd and their lists only partly overlap, the
size of the overlap tells you how many people both of them missed.

| Comparison | Our list | Their list | Appeared on both | Implied undercount |
|---|---:|---:|---:|---|
| Healthcare | 1,057 | 910 | 194 | **5.9×** |
| Education | 508 | 597 | 93 | **8.1×** |
| Government | 443 | 617 | 95 | **8.2×** |

So roughly **7 real attacks for every 1 that appears on a leak site.**

### Then a second method disagreed

US healthcare providers are *legally required* to report breaches affecting 500+
people. That registry is therefore nearly complete — so we can simply ask what
fraction of it appears on leak sites.

The answer is **4.6%**, which implies an undercount of **22×**, not 7×.

**We published the lower number.** Both methods are imperfect in opposite directions,
and we chose the conservative one. The honest consequence, stated plainly:

> **Our risk figures are more likely to be too low than too high.**

That is a stronger thing to be able to say than a confident single number would be.

---

## 5. What this cannot tell you

Said upfront, because someone will ask:

1. **It measures attacks that became public, not all attacks.** For 65% of records the
   "attack date" is really the date the criminals posted about it. Companies that quietly
   paid never appear anywhere.
2. **Read the ranking, not the exact numbers.** The undercount correction multiplies
   every industry equally, so it shifts all the numbers together while leaving the order
   alone. We checked this: the industry ranking is **identical in all 14 positions**
   whether you use raw counts or fully corrected ones.
3. **"Business Services" is not a real category.** It lumps together 1.79 million firms
   from consultancies to one-person estate agents. Its number is close to meaningless.
4. **Company-size risk is a single curve applied to every industry.** Only 65 US records
   state an employee count, which is not enough to produce 14 separate curves. The
   smallest size band — 63% of all US firms — rests on just 7 records.
5. **One year of usable data.** Only 2025 has complete coverage across all 14 industries,
   so there is no trend here yet.
6. **Costs are not like-for-like.** One figure may be total business cost, another
   recovery spending, another a regulatory fine. Each has its source attached. Do not
   add them up.

### A sanity check we passed

US insurers (via the NAIC) report a **1.14%** claim rate for cyber insurance overall in
2024. Ransomware is one type of cyber incident among many, so our **0.40%** should sit
below that — and it does. We used this only as a check, never as a target.

---

## 6. How reliable is the detail?

Every one of the 565 researched incidents has at least one published source. But not
every incident has every detail, because companies are not required to say:

| Detail | Available |
|---|---|
| At least one cited source | 565 of 565 (100%) |
| What data was affected | 328 (58%) |
| Downtime or recovery detail | 323 (57%) |
| A ransom figure | 136 (24%) |
| A total cost figure | 90 (16%) |

Blank does not mean zero. It means nobody published a number. Researchers were
instructed never to estimate a figure they could not point to a source for.

### Two mistakes we found and fixed

Worth including because they show the checking is real, and because both looked
completely plausible:

**The biggest ransom in the dataset was wrong by 10×.** A record said Kaseya paid
$700 million. That figure was actually REvil's total earnings across 2,500 attacks,
quoted in a court sentencing report — the software that read the article attached the
gang's lifetime total to the one company it named. The real demand was $70 million.
A second case gave Bank of America a $144 million ransom that was really LockBit's
lifetime total, from an article not about Bank of America at all. We removed 46
records with this problem and added a check to stop it recurring.

**Four large losses were understated by a factor of a million.** Our figure reader
handled "$70 million" correctly but not "$70-75 million", where the word "million"
comes after the second number — so it recorded **$70**. This affected Norsk Hydro,
Maersk ($200M), Progress Software and United Natural Foods ($350M). Fixed and covered
by tests.

Neither was found because a number looked odd. **$700 million looked entirely
reasonable.** They were found by counting records and reading the top of every list.

---

## 7. Where the data lives

| | |
|---|---|
| **Interactive site** | [fierydeveloper.github.io/CNA_Ransomware](https://fierydeveloper.github.io/CNA_Ransomware/) — 7 tabs, including **Frequency** for the risk figures |
| **Database** | MongoDB Atlas, 12 collections, all 41,644 records |
| **Knowledge graph** | Neo4j, for exploring connections between victims, attackers and industries |
| **Raw files** | `data/` in this repository |

Everything regenerates from scripts — nothing here is hand-typed into a spreadsheet.
The three commands that produce the risk figures:

```bash
python scripts/fetch_exposure.py            # how many firms exist (Census)
python scripts/estimate_underreporting.py   # how much is being missed
python scripts/build_frequency.py           # the risk table
```

Every number the model produces is labelled with where it came from:
**measured** (from a source), **estimated** (calculated with stated method),
**assumed** (our judgement, declared), or **derived** (arithmetic on the above).
There are 10 assumptions and 8 known limitations, each written down with which
direction it would bias the result.
