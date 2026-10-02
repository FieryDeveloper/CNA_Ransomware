# Ransomware Industry Dataset — 10 Minute Walkthrough

A briefing doc for explaining what this database is, what's in it, and where it came from.
For file formats and how to re-run the pipeline, see [README.md](README.md).

---

## 1. The one-sentence version

> We scraped public ransomware leak-site trackers to get **who got attacked and in what industry**, then researched each notable victim in the press to find **what it actually cost them** — and organised the whole thing into a taxonomy of *what threatens each industry* and *what each industry has exposed*.

The gap this fills: leak-site trackers tell you a company was hit but nothing about impact. Press reporting has impact but isn't structured. This joins the two.

**Then it answers the question neither of them can.** Counting attacks tells you who
gets hit *often*; it cannot tell you how *likely* any one firm is to be hit, because a
count has no denominator. Dividing by Census firm counts turns "Manufacturing had 581 US
victims" into "a manufacturer carries roughly 22x the risk of a restaurant" — which is
the form an underwriter can actually price. See §7c.

---

## 2. Coverage — the numbers people will ask for

| Question | Answer |
|---|---|
| How many industries? | **14** (Verizon DBIR-aligned) |
| How many records in total? | **41,644** across five layers |
| How many victims scraped? | **27,108** leak-site postings |
| How many researched incidents? | **565** |
| How many distinct companies? | **561** |
| How many ransomware groups represented? | **185** in the researched layer, **337** in the scrape |
| Countries covered? | **87** in the researched layer, **183** in the scrape |
| Time span? | **2017–2026**, concentrated in 2023 |
| US vs non-US? | 230 / 218, with 117 undisclosed — near even |
| Taxonomy size? | 94 hazard + 90 exposure categories, **984 subcategories** |
| Industry loss statistics? | **179**, each with a named source |
| Sources cited? | **898 unique URLs** |
| Can it give an attack **rate**? | Yes — **0.40%/firm/year** US central, segmented by industry and firm size |

**Three more victim lists sit alongside the scrape**, deliberately unmerged:
**5,942** Comparitech tracker incidents (623 with a ransom amount), **7,925** HHS OCR
mandatory healthcare breach reports (2009–2026), and **104** ransomware families with
on-chain ransom **paid** ($336.4M). Keeping them separate is what makes it possible to
measure how much they are all missing — see question 7.

**The scrape behind it is 48× bigger.** The 565 are researched exemplars sitting on top of **27,108 scraped leak-site victims** across all 14 sectors, 2015–2026 (Business Services 5,209 · Manufacturing 4,439 · Technology 3,146 · Healthcare 2,444 · …). The 565 are simply the ones where impact was *publicly reported* — the scrape gives you frequency, the researched layer gives you severity. Quote them separately; they are not interchangeable.

**Honest coverage caveat:** every incident has a source, but not every field is filled:

| Field | Filled | Why the gap |
|---|---|---|
| Cited source | 565/565 (100%) | — |
| Downtime / recovery | 332 (59%) | usually reported in press |
| Data impact | 330 (58%) | breach-notification laws force it |
| Ransom demanded/paid | 172 (30%) | rarely disclosed voluntarily |
| Financial impact | 141 (25%) | only public companies must disclose |

Blank means *"not publicly disclosed"* — a real reporting gap, not missing work. Agents were told never to estimate a figure they couldn't source.

**And one caveat about the dollar figures specifically.** 46 records were removed from
this dataset after review because the classifier had attributed a *gang's lifetime
total* to a single named victim — articles about sentencings and bounties quote
figures like "linked to more than $144 million in ransom payments", which is LockBit
across all victims, not that company's ransom. The two largest ransom figures in the
dataset were both this bug. If you extend the dataset with `ingest.py`, note that it
now rejects victim names that are descriptions rather than organisations, which is
what let those records in.

---

## 3. Five example incidents

Picked to show the range — different industries, different loss shapes.

1. **Change Healthcare** (Healthcare, ALPHV/BlackCat, Feb 2024) — **~$2.9bn** total impact to UnitedHealth for FY2024. Disrupted roughly a third of US patient records via one claims clearinghouse. *The concentration-risk poster child.*

2. **CDK Global** (IT/SaaS, BlackSuit, Jun 2024) — **>$1bn** in dealer losses (Anderson Economic Group) from ~2 weeks down. CDK itself was the victim; ~15,000 auto dealerships bore the cost. *Third-party aggregation risk.*

3. **MGM Resorts** (Hospitality, ALPHV/Scattered Spider, Sep 2023) — **~$100m** EBITDAR hit, ~10 days with slot machines, digital keys and reservations down. *Social-engineering entry, pure business interruption.*

4. **United Natural Foods (UNFI)** (Food distribution, Jun 2025) — **$350–400m** net sales reduction, $50–60m net income. *Shows how thin-margin distribution amplifies an outage.*

5. **HSE Ireland** (Public health, Conti, May 2021) — **>$600m** recovery cost, months of disruption, ransom **not paid**. *Public sector: refusing to pay moves the loss into recovery cost, it doesn't remove it.*

Others worth having in your pocket: ICBC (Treasury market disruption), CommonSpirit (~$160m), JBS ($11m paid), Colonial Pipeline, Maersk/NotPetya (~$300m — the costliest cyber loss on record), KNP Logistics (ransomware-caused insolvency, ~730 jobs).

---

## 4. Five hazard categories — *what threatens an industry*

The threat side. Every industry gets these, but the contents differ sharply.

1. **Initial access vectors** — how they get in: unpatched edge/VPN appliances, stolen credentials from infostealer logs, phishing, MSP compromise.
2. **Extortion tactics** — the pressure mechanism: encryption, data exfiltration (double extortion), patient/customer harassment, DDoS layering, re-victimisation.
3. **Third-party / supply-chain risk** — vendors, clearinghouses, SaaS platforms, MSPs. Where one intrusion becomes thousands of victims.
4. **OT / operational risk** — physical process disruption: ICS/SCADA in manufacturing and energy, medical devices in healthcare, fleet telematics in transport.
5. **Regulatory exposure** — HIPAA vs GLBA/DORA vs FERPA vs CIRCIA. Determines how much post-incident cost is legal rather than technical.

*(Also present: insider risk, ransom-payment/sanctions risk, and industry-specific ones — e.g. Education has "initial access via open and federated campus environments" with 9 subcategories.)*

---

## 5. Five exposure categories — *what's actually exposed*

This answers the meeting-note question **"eg healthcare company, what is exposed to a ransomware attack?"** Deliberately concrete — real system names, not abstractions.

1. **Healthcare** → EHR platforms (Epic, Cerner, MEDITECH), PACS/imaging archives, lab information systems, claims clearinghouses, medical IoT and infusion pumps, patient PHI.
2. **Manufacturing** → PLCs and distributed control systems, SCADA/HMI, Manufacturing Execution Systems, production-tied ERP, CAD/CAM files and firmware source code.
3. **Education** → Student Information Systems, LMS (Canvas, Blackboard, Moodle), gradebooks, financial aid/bursar/FAFSA records, minors' PII, research IP.
4. **Finance** → core banking, payment rails (ACH, wire, SWIFT, card networks), KYC/AML records, card PANs, Banking-as-a-Service providers and their downstream fintechs.
5. **Energy** → SCADA/RTUs at substations and pipelines, DCS at plants, energy-trading platforms, fuel-retail POS (Suncor: 1,500+ stations to cash-only).

Same skeleton across all 14 industries — that's what makes them comparable. The contents are what make them useful.

---

## 6. Five aggregate statistics

From [synthesis.json](data/synthesis.json), all sourced:

1. **~$820m** total on-chain ransom payments in 2025 — lowest since 2021, down 8% YoY *(Chainalysis 2026)*
2. **$59,556** median on-chain payment, up **368%** from $12,738 *(Chainalysis 2026)* — fewer victims paying, but much larger payments
3. **~28%** of demands paid in 2025, potentially an all-time low *(Chainalysis 2026)*
4. **7,874** victims posted to leak sites in 2025, **+50% YoY**, most active year on record *(Chainalysis, citing eCrime.ch)*
5. **$1.7m** average recovery cost; **53%** recover within a week *(Sophos State of Ransomware)*

The headline story in one line: **attacks up sharply, payment rates down, but payment sizes way up.**

> ⚠️ If someone cites *"24 days average downtime"* — that traces back to 2022 Statista data and is stale. We deliberately excluded it and used Sophos's verified "53% recover within a week" instead.

---

## 7. What we scraped, and why those sources

Three public trackers were evaluated. **They are not interchangeable.**

| Source | Verdict | Why |
|---|---|---|
| **ransomware.live** | ✅ Base data | The only free tracker that tags victims with an **industry sector** *and* carries per-incident fields (ransom, press links, data size, country). Free API, no auth. |
| **RansomLook** | ⚠️ Corroboration only | Group-centric — no victim-by-sector endpoint. Search API is now retired. |
| **ransomwatch** | ⚠️ Corroboration only | Only post title/group/timestamp. No sector tags. **Feed is stale — last post June 2025.** |

Since neither backup classifies by industry, ransomware.live became the spine and the others were cross-checks.

**Impact data was not scraped** — leak sites don't publish it. It came from per-incident research of press coverage, breach notifications, regulatory filings and company statements.

**One gotcha worth mentioning if anyone rebuilds this:** the endpoint `/v2/victims/sector/{sector}` returns **HTTP 200 with an HTML docs page**, not a 404. A naive scraper silently produces an empty dataset and looks like it worked. The real route is `/v2/sectorvictims/{sector}`. Our fetcher now rejects any response starting with `<`.

---

## 7b. The finding the visualization made obvious

Open [explorer.html](explorer.html) and stay on the **Matrix** tab. Rows are categories, columns are the 14 industries.

The shape of it *is* the argument:

- **Hazards form a dense block.** Grouped into families, five of them — initial access, extortion, insider/workforce, third-party/supply chain, regulatory — reach **all 14 industries**. OT/operational disruption reaches 13.
- **Exposures are sparse and scattered.** **83 of 86 appear in exactly one industry.**

> **How you get attacked is nearly universal. What you stand to lose is almost entirely industry-specific.**

This is a useful thing to say to an underwriting audience, because it splits cleanly: controls generalise across a portfolio, loss modelling does not. It also justifies why the taxonomy has two axes instead of one — and it wasn't visible in the CSV at all.

*(Caveat if you present the family view: the hazard families come from a keyword map, so they're an interpretive layer. "As reported" is one click away and the raw labels are never overwritten.)*

---

## 7c. From counts to a rate — the part that took the most care

Everything above is a **numerator**. The frequency model divides by a denominator:
**6.5M US employer firms** from Census SUSB, crosswalked to the 14 sectors by NAICS code.

| Industry | 2025 US victims | Firms | Rate per 10,000 firms/yr |
|---|---:|---:|---:|
| Telecommunication | 44 | 12,086 | **274** |
| Energy and Utilities | 71 | 24,113 | **222** |
| Manufacturing | 581 | 202,208 | **216** |
| Healthcare | 365 | 693,801 | **32** |
| Construction | 295 | 782,487 | **29** |
| Hospitality and Tourism | 90 | 723,013 | **10** |
| **All industries** | **3,459** | **6,517,587** | **40** (= 0.40%/yr) |

Note what the denominator does to the ranking. Healthcare took **5x more victims** than
Energy (365 vs 71), yet Energy's **rate is 7x higher** — because Healthcare has 693,801
firms against Energy's 24,113. By count, Healthcare looks like one of the worst-hit
sectors; by rate it sits in the bottom half. Construction is the same story in miniature:
alarming by count (295), benign by rate (29), because 782,487 mostly-tiny contractors sit
in the denominator.

**Three things to say before anyone asks:**

1. **This measures how often a firm gets *listed on a leak site*, not attacked.** For 65%
   of records the attack date equals the discovery date, so the date is really the posting
   date. Quiet payers never appear at all.
2. **Leak sites undercount by roughly 7x, and that figure is *measured*, not assumed.**
   Two independently-built victim lists overlap partially; how much they overlap tells you
   how much both are missing (capture–recapture). A second route using healthcare's
   *mandatory* HHS reporting suggests the undercount could be 20x+, so our published
   numbers are more likely too low than too high.
3. **Read the ranking, not the level.** The undercount multiplier scales every industry
   together, so it moves the level but cancels out of the ordering. The ordering is
   identical in all 14 positions whether you use the raw observed counts or the fully
   adjusted ones — that is checked, not asserted.

Sanity check for the sceptic in the room: the NAIC reports a **1.14%** all-cyber insurance
claim frequency for 2024. Ransomware is a subset of all-cyber, so our 0.40% landing below
it is the expected result. It is used as a check, never as a target to fit to.

**Open the Frequency tab in [explorer.html](explorer.html)** — the rate table, the size
curve, the undercount derivation, and every assumption tagged measured / estimated /
assumed.

---

## 8. What is the taxonomy based on?

- **Industry list:** Verizon DBIR sector groupings (NAICS-aligned), mapped onto ransomware.live's own `activity` tags. Chosen because DBIR is what the team already references and it makes this comparable to external benchmarks.
- **Hazard/exposure split:** hazards = *what can happen to you*; exposures = *what you have that can be hit*. Standard risk-modelling separation of threat from asset — it lets you assess a company by inventorying what it owns, without predicting attacker behaviour.
- **Per-industry derivation, not a template.** Each industry's categories were derived from its own incident data. That's why Healthcare surfaces PACS and claims clearinghouses while Manufacturing surfaces PLCs and MES. A shared template would have flattened exactly the differences the project is trying to measure.
- **Statistics:** Sophos *State of Ransomware*, Coveware Quarterly, IBM *Cost of a Data Breach*, Verizon DBIR, Chainalysis *Crypto Crime Report*.

---

## 9. Can this be automated with agents?

**Yes — it already was.** That's how it was built: one research agent per industry, running in parallel, each pulling API data, cross-checking trackers, researching incidents, and returning a schema-validated JSON record. ~14 agents, ~1.6m tokens, ~880 tool calls.

**What automated well:**
- Fanning out per industry — 14 parallel agents instead of 14 sequential passes
- Schema-enforced output, so records merge without cleanup
- Web research per incident — the slow, tedious part
- Deriving per-industry taxonomies

**What needed human judgment:**
- **Endpoint verification.** Agents given a wrong endpoint mostly self-corrected — but not all did, and the failure was silent (200 + HTML). Machine-checkable guards matter more than agent diligence here.
- **Conflicting sources.** One agent found a cumulative damages figure reported as both $2.54bn and $9.45bn for the same page and omitted it rather than pick one. That's the right call, but it needs a human to ratify.
- **Stale statistics.** The "24 days downtime" figure looks authoritative and propagates widely. Catching it required tracing citations to origin.
- **Uneven grounding.** One industry's data pull failed entirely and it fell back to news research — still valid, but not comparable. You only catch that by auditing.

**Practical takeaway for scaling:** agents handle breadth well and are genuinely good at the research grind. They need (a) hard validation on data ingestion, since silent failures look identical to success, and (b) a coverage audit at the end. Both are cheap and already scripted here — [validate.js](scripts/validate.js) does exactly this.

**To refresh quarterly:** re-run the fetchers, re-run the incident research for new leak-site entries, rebuild. The taxonomy is stable; the incident and statistics layers are what age.

---

## 10. Known limitations — say these before someone asks

1. **Leak-site data undercounts.** Only victims groups *chose to publish*. Quiet payers and non-leak-site groups are invisible. Counts are a floor.
2. **Public Sector is counted in a different unit.** Its scrape is now complete (1,279
   victims), but NAICS 92 is absent from Census SUSB entirely, so its denominator is
   **90,887 governments** rather than firms. One county is one unit while running many
   separately attackable agencies, so that rate must never share an unlabelled column
   with the firm-based ones.
3. **Financial figures aren't like-for-like.** A "cost" may be total incident cost, an insurance estimate, a fine, or an analyst estimate. Check the `source` column before aggregating.
4. **Sector-level loss figures lean on surveys**, not incident disclosure — because disclosure is so sparse. In the Education pull, only 13% of records had a press link and 0.9% a ransom figure.
5. **Sector tags are the tracker's, not a standard.** Occasionally inconsistent upstream (`Consumer Services` and `Consumer services` both appear).
6. **Four industry records** (Public Sector, Agriculture, Technology, Telecommunications) completed while the automated output classifier was unavailable and didn't get that secondary review. Sourcing is present and checkable — spot-check before anything load-bearing.
7. **The size dimension is the weakest part of the frequency model.** Only 227 records
   carry an employee-count label and just 65 are US, so one pooled size curve is applied
   to all 14 industries and the size×industry interaction is explicitly *assumed absent*.
   The smallest band — 63% of all US firms — rests on 7 records.
8. **"Business Services" is not risk-homogeneous.** It spans five unrelated NAICS sectors
   and 1.79M firms, including 366K micro-realtors. Its headline rate is close to
   meaningless; use the constituent NAICS codes.
9. **One usable year.** Only 2025 has complete 12-month coverage across all 14 sectors, so
   there is no trend and no credibility weighting. The 2024→2025 instability is itself a
   warning that the tracker's sector tagging is not stable across refreshes.

---

## Suggested 10-minute running order

| Min | Cover |
|---|---|
| 0–1 | §1 one-sentence version — the leak-site/press gap this closes |
| 1–3 | §2 coverage numbers, incl. the honest field-coverage table |
| 3–5 | §3 five incidents — lead with Change Healthcare and CDK |
| 5–7 | §4 + §5 the two taxonomy axes; use healthcare vs manufacturing to show why per-industry matters |
| 7–8 | **Open [explorer.html](explorer.html) on the Matrix tab** — §7b, let the shape make the point |
| 8–9 | **§7c the rate** — Frequency tab; make the Healthcare-vs-Manufacturing denominator point |
| 9–10 | §9 automation answer + §10 top two limitations |

If you only have five minutes, cut §4–§6 and go straight from §2 to §7c: the
count→rate step is the part people have not seen elsewhere.

If you only have five minutes: open the matrix, say the one-sentence version (§1), then the hazard/exposure asymmetry (§7b). That's the whole project in two moves.
