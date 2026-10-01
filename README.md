# Ransomware Industry Risk Dataset

A structured dataset mapping ransomware risk across industries: **who gets hit, what is exposed, what it costs, and how long recovery takes**. Built to support the hazard/exposure taxonomy work described in the project meeting notes.

Base incident data comes from public ransomware leak-site trackers. Each notable incident was then supplemented with web research into what was actually reported publicly — revenue loss, ransom demanded/paid, downtime, records affected — with every figure carrying a source URL.

---

> **Explaining this to someone?** See [EXPLAINER.md](EXPLAINER.md) — a 10-minute walkthrough with worked examples, coverage answers, and the automation question.

## What's in here

```
explorer.html          ← self-contained interactive explorer; open in any browser

data/
  industries.json      full nested record per industry (the master file)
  incidents.csv        one row per researched real-world attack
  taxonomy.csv         hazard + exposure categories, long format
  aggregate_stats.csv  industry-level loss/frequency figures, each with a source
  synthesis.json       cross-industry comparison + global loss statistics
  sources.txt          every distinct URL cited
  raw/                 unprocessed API pulls (created by the fetch scripts)
  graph/               knowledge-graph export: node/rel CSVs, load.cypher, queries.cypher, style.grass
  mongo/               the 11 MongoDB collections as JSON, ready for Atlas
  naics_crosswalk.json ransomware.live sector -> NAICS map (the frequency model's join)

scripts/
  fetch_ransomware_live.py   pull victims from ransomware.live (by sector or by year)
  fetch_ransomlook.py        pull RansomLook / ransomwatch corroboration data
  build_dataset.js           assemble agent output into the final dataset
  validate.js                coverage + integrity checks on the built dataset
  export_graph.js            reshape into a knowledge graph (Neo4j + explorer feed)
  build_explorer.js          regenerate explorer.html with data inlined (incl. Insights tab)
  export_mongo.js            shape the dataset into the 8 narrative MongoDB collections
  load_mongo.py              upsert the collections into Atlas + build indexes
  server.js                  Node: serve explorer.html + live insights from Atlas
  embed_graph.py             add per-type local-embedding vector indexes to Neo4j
  ingest.py                  classify raw incident text into the schema (LLM) -> industries.json
  fetch_sec.py               pull SEC 8-K cyber filings, classify + enrich attacker from ransomware.live
  fetch_ransomwhere.py       on-chain ransom-PAID per group (Ransomwhere) -> groups collection
  fetch_exposure.py          Census SUSB firm counts by NAICS x size -> the rate DENOMINATOR
  estimate_underreporting.py capture-recapture vs Comparitech -> measured under-reporting R
  fetch_hhs_ocr.py           HHS OCR mandatory healthcare breach list (JSF/PrimeFaces scrape)
  build_frequency.py         numerator / denominator -> the industry x size frequency table
  rag_core.py                the GraphRAG engine (routing + retrieval + synthesis)
  api.py                     FastAPI: POST /api/ask + live insights (the production API)
  ask.py                     CLI front end to the same engine
```

## Two layers of data

Worth being precise about, because the numbers differ by two orders of magnitude:

| Layer | Size | What it is |
|---|---|---|
| **Bulk scrape** | **27,108 victims** across all 14 sectors, 2015–2026 | Every leak-site posting, sector-tagged. Names, groups, dates, countries — but almost no impact data (only ~13% carry a press link, ~1% a ransom figure). |
| **Researched incidents** | **625** | Hand-researched and harvested exemplars with financial loss, ransom, downtime and recovery, each cited. These are the ones where impact was publicly reported. (107 hand-researched + 518 from SEC 8-K and security-news harvesting.) |

The taxonomy is derived from both. Quote 27,108 for frequency and the 625 for severity — they are not interchangeable.

For an actual **rate** rather than a count, see [The frequency model](#the-frequency-model-industry--size) below: 27,108 is a numerator, and a numerator alone cannot say how likely an attack is.

Sector totals (leak-site postings, 2015 – July 2026):

| Sector | Victims | Sector | Victims |
|---|---:|---|---:|
| Business Services | 5,209 | Construction | 1,362 |
| Manufacturing | 4,439 | Transportation/Logistics | 1,331 |
| Technology | 3,146 | Education | 1,298 |
| Healthcare | 2,444 | Public Sector | 1,279 |
| Consumer Services | 1,783 | Agriculture & Food | 1,220 |
| Financial Services | 1,643 | Energy | 826 |
| Hospitality & Tourism | 771 | Telecommunication | 357 |

A further 2,748 postings carry the sector value `Not Found` (unclassified upstream) and are excluded from the per-sector figures above. The year-by-year pull totals 29,888 rows including those.

## Dataset at a glance

| | |
|---|---|
| Industries | 14 |
| Researched incidents | 625 |
| Hazard categories | 94 |
| Exposure categories | 90 |
| Taxonomy subcategories | 984 |
| Aggregate loss/frequency stats | 179 |
| Unique cited sources | 376 |

**Incident coverage** — every one of the 625 incidents carries at least one cited source URL. 335 (54%) have downtime/recovery detail, 345 (55%) describe data impact, 157 (25%) carry a ransom figure (92 of them parsed to a number) and 99 (16%) a financial-impact figure (71 parsed). The rest are marked *"not publicly disclosed"*, which is a genuine public-reporting gap, not missing research — agents were explicitly instructed never to estimate a figure they could not source. Coverage rates are lower than at 107 incidents because the bulk SEC/news harvest reaches further down the disclosure tail, where fewer numbers are ever published.

**Spread** — incidents run 2017–2026, weighted toward 2023–2026, and split almost evenly between US (53) and non-US (54) organisations. Most-represented groups: LockBit, Conti, Qilin, ShinyHunters, REvil/Sodinokibi, INC Ransom, Clop, Everest.

---

## Data sources, and why

Three public trackers were evaluated. They are **not** interchangeable:

| Source | Role | Why |
|---|---|---|
| **ransomware.live** | Base data (the sector spine) | The only free tracker that tags each victim with an **industry sector** *and* carries per-incident fields (`ransom`, `press`, `data_size`, `country`, `attackdate`). Free v2 API, no auth, 1 req/min per endpoint. |
| **RansomLook** | Corroboration | Public API is **group-centric** — no victim-by-sector endpoint. Useful for confirming a victim was posted and widening group coverage. |
| **ransomwatch** | Corroboration | `posts.json` carries only `post_title`, `group_name`, `discovered`. No sector tagging. |

Because neither corroboration source classifies victims by industry, ransomware.live was used as the industry spine and the other two as cross-checks. The canonical sector list was pulled from `/v2/sectors` first so that industries map onto **Verizon DBIR-style groupings** rather than each being invented ad hoc.

### API gotchas found the hard way

- **The sector route is `/v2/sectorvictims/{sector}`.** The plausible-looking `/v2/victims/sector/{sector}` does *not* 404 — it returns **HTTP 200 with the API's HTML documentation page**. A loose parser will silently yield an empty or garbage dataset. `fetch_ransomware_live.py` rejects any response body starting with `<` for this reason.
- **`Transportation/Logistics` is unreachable by sector.** The slash in the sector name breaks the path and 404s under every encoding tried (raw, `%2F`, `%252F`, space, hyphen, `+`). The public `/activity/{sector}` page is a client-rendered SPA shell and carries no data either. **Workaround: pull `/v2/victims/{year}` for each year and group on the `activity` field** (`--years 2015-2026`). That reaches every sector and cross-checks the per-sector counts.
- **`/v2/victims` and `/v2/allvictims` return HTML**, but `/v2/victims/{year}` and `/v2/countryvictims/{code}` return real JSON. Endpoint naming is inconsistent — probe before trusting.
- **Rate limiting is per-endpoint, not global.** Distinct paths can be fetched back-to-back; the same path needs ~60s between calls.
- **RansomLook's search API is retired** (400/404/405 across GET and POST variants).
- **`ransomwhat.telemetry.ltd/posts.json` 302s to an HTML landing page.** The feed is recoverable from the project's canonical GitHub raw file (~16,000 posts), but its **last post is 16 June 2025** — it is stale and usable only for corroboration, never for counts.
- `curl` failed with error 43 / HTTP 000 in some sandboxes; PowerShell `Invoke-WebRequest` and Python `urllib` both worked.
- PowerShell 5.1's `ConvertFrom-Json` aborts on this dataset — the nested `infostealer_stats` object contains both `RedLine` and `Redline`, which collide case-insensitively. Parse in Python or Node.

Incident-level financial and downtime data does **not** come from these trackers — leak sites don't publish it. It was gathered by researching press coverage, breach notifications, regulatory filings, and company statements per incident.

---

## The taxonomy

Two axes, derived **per industry** rather than templated — which is the point of the exercise.

**Hazard categories** — the threat side. Typically: initial access vectors, extortion tactics, third-party/supply-chain risk, OT/operational risk, insider risk, regulatory exposure. How these actually manifest differs sharply by industry.

**Exposure categories** — the *"what is exposed out there"* question from the meeting notes. This is deliberately concrete:

- *Healthcare* → EHR systems, PACS/imaging, medical IoT and infusion pumps, telehealth platforms, claims clearinghouses, patient PHI
- *Manufacturing* → OT/ICS/SCADA, production-line systems, vendor networks, IP and trade secrets
- *Education* → student information systems, LMS, financial aid/bursar systems, research IP, minors' PII, edtech vendors
- *Finance* → core banking, payment rails, trading systems, KYC/AML records, third-party fund administrators

The same structure across all industries is what makes them comparable; the contents are what make them useful.

---

## Reproducing / extending

```bash
# 1. Pull base victim data (free tier is paced at 1 req/min — slow but works)
python scripts/fetch_ransomware_live.py --all-sectors
python scripts/fetch_ransomware_live.py --sector Healthcare   # single sector

# Optional: a free PRO key lifts the rate limit to 500k calls/month
export RANSOMWARE_LIVE_API_KEY=...   # from https://my.ransomware.live

# 2. Pull corroboration data
python scripts/fetch_ransomlook.py --ransomwatch
python scripts/fetch_ransomlook.py --search "university"

# 3. Rebuild the dataset from agent output
node scripts/build_dataset.js <path-to>/journal.jsonl
node scripts/build_dataset.js --from-dir data/agents

# 4. Check coverage and integrity
node scripts/validate.js

# 5. Rebuild the knowledge graph and the interactive explorer
node scripts/export_graph.js      # -> data/graph/ (Neo4j CSVs + load.cypher)
node scripts/build_explorer.js    # -> explorer.html
```

### Complete coverage (recommended)

Per-sector pulls cannot reach `Transportation/Logistics`. Pull by year instead — this
covers every sector and gives you the counts to cross-check against:

```bash
python scripts/fetch_ransomware_live.py --years 2015-2026 --skip-existing
```

### Viewing the data

- **[explorer.html](explorer.html)** — open in a browser. Matrix view first: rows are
  categories, columns are industries. It shows at a glance that hazards are shared across
  industries while exposures are almost entirely industry-specific.
## Visualizing in Neo4j

Worth it for the ~27k victim layer, where Cypher beats spreadsheet joins. For the taxonomy
alone, the matrix in `explorer.html` is more legible than any force graph.

**1. Get an instance.** Easiest is [Neo4j Desktop](https://neo4j.com/download/) (free, local).
Create a project, add a **Local DBMS**, set a password, and start it. Neo4j Aura Free works
too, but loading local CSVs is harder there, so Desktop is the smoother path.

**2. Put the CSVs where Neo4j can read them.** Neo4j only reads from its own import folder.
In Desktop: click the **⋯** next to your database → **Open folder** → **Import**. Copy every
file from `data/graph/` into it:

```bash
cp data/graph/*.csv "<the import folder you just opened>"
```

**3. Load.** Open **Neo4j Browser** (the *Open* button), then paste the contents of
[load.cypher](data/graph/load.cypher) into the query bar and run it. It creates the
constraints, loads the curated taxonomy, then batch-loads the 27k victims.

The last block is Neo4j 5 syntax. On 4.x, replace the `CALL { … } IN TRANSACTIONS OF 1000 ROWS`
wrapper with `:auto USING PERIODIC COMMIT 1000` before the `LOAD CSV`. Loading the bulk layer
takes a minute or two; skip that final block if you only want the taxonomy.

**4. Draw something.** This is the part that trips people up: **Neo4j Browser only renders a
picture when your query returns nodes, relationships, or paths.** Return a count or a string
and you get a table instead. So start with:

```cypher
MATCH p = (:Industry)-[:FACES]->(:Hazard)
RETURN p;
```

[queries.cypher](data/graph/queries.cypher) is split accordingly: **Part 1** is six visual
queries (whole taxonomy skeleton, one industry in full, shared hazards between two industries
as a bowtie, cross-sector groups, exposure drill-down, bulk victims by group). **Part 2** is
analytical queries that return tables.

**5. Apply the stylesheet.** **Drag [style.grass](data/graph/style.grass) onto the Neo4j Browser
window.** This is the single biggest readability win: without it every node is the same grey
circle labelled with an internal id.

It encodes the hierarchy in size and colour, matching `explorer.html`:

| Level | Label | Colour | Size |
|---|---|---|---|
| 1 | `Industry` | graphite | largest |
| 2 | `Hazard` | oxblood (warm = what happens to you) | large |
| 2 | `Exposure` | navy (cool = what you own) | large |
| 3 | `Subcategory` | sand | small |
| evidence | `Incident` | bronze | large |
| evidence | `Group` | plum | medium |
| bulk | `Victim` | pale grey | smallest |

Captions are set per label too, so nodes show real names rather than ids.

**6. Read the graph.** [queries.cypher](data/graph/queries.cypher) has three sections. **Part 1b
is the one you want** — eight queries that each return a subgraph small enough to read like a
sentence:

- **S1** is the clearest single picture: one incident with everything attached. It reads as
  *"Healthcare had an incident at Change Healthcare, committed by ALPHV/BlackCat, in the US,
  evidenced by these sources."* Swap the victim name for any other.
- **S3 then S4** are the project's headline as two pictures. S3 (hazards shared by 10+
  industries) draws a dense hub. S4 (the same query for exposures) comes back nearly empty.
  Run them back to back and the asymmetry is undeniable on screen.
- **S5** shows how one industry differs: Manufacturing's exposures drilled to specifics gives
  you OT/ICS/SCADA and production systems, not patient records.
- **S6** traces one group's footprint across industries; **S7** isolates the supply-chain
  aggregation cases; **S8** shows only incidents with a disclosed dollar figure.

Bump the node cap in ⚙ settings if a query truncates at 300.

> **Never run `MATCH (n) RETURN n`.** There are 27,108 `:Victim` nodes; the browser will hang,
> and a 30k-node hairball conveys nothing anyway. Always filter to a group, sector, or industry
> first, and keep a `LIMIT` on anything touching `:Victim` (query V6 shows the pattern).

### If you want true whole-graph exploration

Browser is a query tool that happens to draw pictures. For roaming the graph without writing
Cypher, use **Neo4j Bloom** (bundled with Desktop: open the instance and pick Bloom instead of
Browser). Create a perspective over `Industry`, `Hazard`, `Exposure` and `Incident`, leave
`Victim` out of it, and you get search-driven exploration with the hierarchy intact. Bloom
handles the scale better and is the friendlier surface for showing someone else.

### The graph model

| Node | Count | Node | Count |
|---|---:|---|---:|
| Industry | 14 | Group | 427 |
| Hazard | 50 | Country | 35 |
| Exposure | 86 | Statistic | 197 |
| Subcategory | 984 | Source | 376 |
| Incident | 625 | Theme | 25 |
| Company | 103 | **Victim** (bulk) | **27,108** |

Relationships: `FACES`, `EXPOSES`, `INCLUDES`, `HAD_INCIDENT`, `HIT`, `PERPETRATED_BY`,
`OCCURRED_IN`, `CITED_BY`, `MEASURED_BY`, `ATTACKED_BY`.

Hazard and exposure categories are **deduplicated by name across industries** — that is what
makes the graph informative. When 14 industries all connect to one `Initial Access Vectors`
node, the universality is visible structurally instead of being buried in 14 near-identical
rows. Subcategories stay per-category, since that is where industry-specific detail lives.

`build_dataset.js` handles two real complications from how this was produced: the research run was interrupted by usage limits and resumed, so results span **multiple runs** (it takes the union), and agents named the same sector inconsistently (it canonicalises names and keeps the **richest** duplicate).

---

## Expanding the dataset (ingest)

New incidents can be classified into the schema from raw text (an SEC 8-K, a news
article, a breach notice). `ingest.py` uses an LLM with a strict JSON schema to
extract our incident fields and classify the victim into one of the 14 industries,
then appends to `data/industries.json` — the single source of truth the whole
pipeline derives from. Dollar parsing and dedup happen on rebuild, so there is one
parser and the derived stores never drift.

```bash
python scripts/ingest.py --file article.txt --dry-run   # preview the classified record
python scripts/ingest.py --url https://www.sec.gov/...   # fetch + strip + classify
cat notice.txt | python scripts/ingest.py                # stdin
# then rebuild: node export_mongo.js && python load_mongo.py ; node export_graph.js ; embed_graph.py
```

The model is told to write "not publicly disclosed" rather than estimate a missing
figure, and to set `is_ransomware_incident=false` for text that isn't a specific
incident — so it won't invent records.

### Where to get more data

| Source | Access | Best for |
|---|---|---|
| **SEC EDGAR full-text search** (`efts.sec.gov`) | API | Financial impact — 8-K Item 1.05 material-cyber filings (since Dec 2023). |
| ~~**Maine AG breach notifications**~~ | **disabled** | Was a clean victim/date/records-affected registry, but Maine took the public portal down after it was hit with fake submissions. **Do not plan around it.** |
| **Washington State AG data-breach report** | PDF + portal | Ransomware *share* of breaches: 2024 saw 279 notifications of which 113 were ransomware-caused. Directional check, not a rate — WA law triggers on any WA resident, so it skews to multi-state and larger firms. |
| **Census SUSB** (`www2.census.gov/.../susb`) | static CSV, no key | Firm counts by NAICS x employment size — the **denominator** for any frequency rate. Already wired up in `fetch_exposure.py`. |
| **NAIC Cybersecurity Insurance Market Report** | PDF | Level validation: ~50,000 cyber claims on 4,368,614 policies in 2024 = 1.14% all-cyber claim frequency. The sanity anchor our ransomware-only rate must sit below. |
| **HHS OCR breach portal** | JSF scrape (wired up) | **7,925 records, 2009-2026.** Mandatory reporting for healthcare breaches affecting 500+ individuals, so near-census within that frame. No API and no CSV: see `fetch_hhs_ocr.py` for the ViewState/TabView/AJAX-paging dance. |
| **California AG breach list** | HTML table | Breach victim + people affected. |
| **ransomware.live** | API (already used) | Victim/group/sector/country/date — the frequency spine. |
| **The Record, BleepingComputer, DataBreaches.net** | HTML/RSS | Ransom paid + downtime narrative (needs LLM extraction). |

ransomware.live gives the *who/when/sector*; SEC + AG lists + news give the *impact*
(the fields the coverage chart shows are sparse). Feed any of them to `ingest.py`.

**SEC 8-K fetcher.** `fetch_sec.py` automates the highest-value source: it queries
EDGAR full-text search for 8-K **Item 1.05** filings (mandatory material-cyber
disclosures since Dec 2023), classifies each via `ingest.py`, and — since filings
rarely name the attacker — **enriches the group by matching the victim against
ransomware.live**. Keeps ransomware + data-extortion; skips accidental breaches.

```bash
export SEC_USER_AGENT="Your Name your@email.com"     # SEC requires a real UA
python scripts/fetch_sec.py --since 2024-01-01 --limit 20 --dry-run
python scripts/fetch_sec.py --since 2024-01-01 --limit 20     # then rebuild
```

**Ransom amounts.** SEC filings and most leak sites don't reveal the ransom, so those
fields stay sparse. The realistic sources:

| Source | Ransom data | Victim-linked? |
|---|---|---|
| **Ransomwhere** (`fetch_ransomwhere.py`) | ~$336M PAID on-chain across 106 groups | no — group-level |
| **ransomware.live bulk** (already pulled) | 137 victim ransom **demands** (Medusa-heavy) | yes |
| **News** (The Record, BleepingComputer) → `ingest.py` | per-victim paid/demanded | yes, but sparse + manual |

`fetch_ransomwhere.py` populates the `groups` collection (ransom paid per group), which the
entity lane surfaces — "tell me about ALPHV" then reports its $21.9M on-chain paid.

---

## MongoDB (Atlas)

The document database is the **source of record + analytics store + app backend**. All the
shaping logic lives in one place (`export_mongo.js`, Node) so there is a single implementation
of the business rules; the Python loader only moves JSON into Atlas and builds indexes.

```bash
node scripts/export_mongo.js          # data/*.json  ->  data/mongo/*.json (8 collections)
python scripts/load_mongo.py --dry-run # validate, no connection needed
python scripts/load_mongo.py           # upsert into Atlas + create indexes
```

**Setup (one time):** create a free M0 cluster at [cloud.mongodb.com](https://cloud.mongodb.com),
add a database user, allow your IP under Network Access, copy the connection string, then:

```bash
export MONGODB_URI='mongodb+srv://USER:PASS@cluster0.xxxx.mongodb.net/'
pip install pymongo
```

### Collections

| Collection | Docs | Shape |
|---|---:|---|
| `industries` | 14 | Curated taxonomy, one doc per industry. Embeds hazards/exposures (with subcategories), aggregate stats, a `bulk_summary`, and `incident_ids` referencing `incidents`. Serves the explorer directly. |
| `incidents` | 625 | Normalized, one per researched attack. `financial` and `ransom` each carry `{text, usd}` — the raw reported string **and** a parsed number, so analytics never re-parse. |
| `victims` | 27,108 | The flat bulk scrape. Indexed on `sector_key`, `group`, `year`, `country` (+ compound `sector_key+year`) so group-bys are fast. |
| `taxonomy` | 136 | Deduped hazard/exposure categories with the industries each spans, its family, and reach. Powers the matrix without recomputation. |
| `insights` | 1 | Materialized dashboard aggregates (by sector/year/group/country, heatmap, parsed losses) so charts never scan 27k rows. |
| `synthesis` | 1 | Cross-industry narrative, themes, global statistics, takeaways. |
| `groups` | 106 | Per-group on-chain ransom **paid** (Ransomwhere), so payment behaviour is a group attribute rather than a per-incident guess. |
| `comparitech` | 5,942 | Comparitech's curated trackers, extracted from their Tableau maps. Kept **independent** of `victims` so the two can be used for capture-recapture. |
| `frequency_exposure` | 127 | Census SUSB firm counts per industry x employee band: the rate **denominator**, stored as fetched so the join is re-checkable. |
| `frequency_calibration` | 1 | The capture-recapture working: A/B/overlap per stratum, Chapman estimates, the dependence sweep, and the published under-reporting schedule. |
| `hhs_ocr` | 7,925 | The HHS OCR breach portal, 2009-2026: healthcare's **mandatory** 500+-individual breach list. The only non-voluntary victim list in the project, which is what makes it usable for calibration. |
| `frequency` | 127 | The frequency table. Four `kind`s: `cell` (104, industry x band), `industry_marginal` (14), `size_marginal` (8) and `method` (1, the audit spine). |

**Idempotent:** every document is keyed by `_id` and replaced in place, so re-running after a
re-scrape updates rather than duplicates.

## The frequency model (industry x size)

Everything above counts attacks. Counts are numerators, and a numerator cannot answer the
question an underwriter actually asks: **how likely is a given firm to be hit?** That needs a
denominator (how many firms exist) and a segmentation (which firms).

```bash
python scripts/fetch_exposure.py           # Census SUSB  -> frequency_exposure.json (denominator)
python scripts/fetch_hhs_ocr.py            # mandatory healthcare list -> hhs_ocr.json
python scripts/estimate_underreporting.py  # capture-recapture -> frequency_calibration.json
python scripts/build_frequency.py          # the model   -> frequency.json
python scripts/load_mongo.py               # into Atlas
```

Stdlib only — no pip install needed for these three.

### Result (2025, US)

Rates are per 10,000 firms per year. `observed` counts only leak-site listings with a confirmed
US country; `central` additionally corrects for country gaps and under-reporting.

| Industry | 2025 US victims | Firms | observed /10k | central /10k | Crosswalk |
|---|---:|---:|---:|---:|---|
| Telecommunication | 44 | 12,086 | 36.4 | 274 | medium |
| Energy and Utilities | 71 | 24,113 | 29.4 | 222 | medium |
| Manufacturing | 581 | 202,208 | 28.7 | 216 | high |
| Technology | 419 | 163,176 | 25.7 | 200 | medium |
| Agriculture and Food Production | 110 | 59,656 | 18.4 | 139 | low |
| Public Sector | 140 | 90,887* | 15.4 | 132 | low |
| Education | 174 | 118,205 | 14.7 | 124 | medium |
| Financial Services | 228 | 244,536 | 9.3 | 71 | high |
| Transportation/Logistics | 126 | 237,527 | 5.3 | 42 | high |
| Healthcare | 365 | 693,801 | 5.3 | 32 | high |
| Construction | 295 | 782,487 | 3.8 | 29 | high |
| Business Services | 523 | 1,791,252 | 2.9 | 22 | **low** |
| Consumer Services | 293 | 1,374,640 | 2.1 | 16 | low |
| Hospitality and Tourism | 90 | 723,013 | 1.2 | 10 | medium |
| **All industries** | **3,459** | **6,517,587** | **5.3** | **40** | |

\* governments, not firms — a different unit (see below).

All-industry central rate is **0.40%/yr** (low 0.32%, high 0.58%). The sanity anchor: NAIC
reports **1.14%** all-cyber claim frequency for 2024. Ransomware is a subset of all-cyber, so
landing below it is the expected result — this is a check, never a fitting target.

### What is measured, and what is modelled

Every number carries a `basis` of `measured`, `estimated`, `assumed` or `derived`, plus
`assumption_ids[]` that resolve in the `method` doc. Nothing is a bare number.

| Layer | Basis | Notes |
|---|---|---|
| Denominator (firm counts) | measured | Census SUSB 2022, NAICS-crosswalked |
| Numerator (2025 US victims) | measured | ~97% have a confirmed country |
| Country adjustment | estimated | +3.5% only — see below |
| Size elasticity b = 0.85 | estimated | weighted R² = 0.90, n = 227 |
| Flat above 1,000 employees | assumed | the power law over-predicts the top band 4x |
| Size x industry interaction | **assumed absent** | 65 US labelled records cannot support 14 curves |
| Under-reporting R | estimated | capture-recapture, 3 of 14 sectors measured |

**Three things worth knowing, because each overturned an assumption we started with:**

1. **BEA does not publish firm counts.** It publishes value added and gross output. Firm counts
   come from Census SUSB, which needs no API key. (BEA gross output is still the right exposure
   base for a *revenue*-rated product — that is a v2 extension.)
2. **The missing-country problem is a 2021-2023 problem, not a 2025 one.** It is 24.9%
   corpus-wide but 86.4% in 2021 and only **3.1% in 2025**. Restricting to 2025 (required anyway,
   since it is the only year with complete 12-month coverage across all 14 sectors) reduces the
   country adjustment from a major correction to a +3.5% footnote.
3. **Under-reporting can be measured rather than assumed.** Two partially-overlapping victim
   lists (leak-site + Comparitech) support a Chapman capture-recapture estimate. It yields
   R = 4.7x (Healthcare), 6.4x (Education), 6.5x (Public Sector) as **hard lower bounds**.

### Why R is a lower bound, and how far up it can go

Chapman assumes the two lists sample independently. They do not: Comparitech partly sources from
leak sites, which inflates the overlap and so deflates the population estimate. But the bias is
**bounded in both directions**, because a record copied from the leak site necessarily matches
it — so leak-sourced records can be at most `M/B` of Comparitech, which is 15-21% by stratum.
Sweeping the sourced fraction over that bounded range gives the published schedule:

| Sourced fraction of overlap | Healthcare | Education | Public Sector | Mean | |
|---|---:|---:|---:|---:|---|
| 0% (lists independent) | 4.68 | 6.37 | 6.45 | **5.8** | published **low** |
| 25% | 5.89 | 8.14 | 8.24 | **7.4** | published **central** |
| 50% | 8.31 | 11.63 | 11.79 | **10.6** | published **high** |
| 75% | 15.48 | 21.82 | 22.14 | 19.8 | unstable, sensitivity only |

The schedule is therefore *derived*, not asserted. (The 5.4 / 7.0 / 12.0 schedule we had assumed
before measuring it is recovered almost exactly, which is reassuring but was not guaranteed.)

### A second route disagrees by 3x, and that gap is the real uncertainty

Everything above leans on Comparitech, a *voluntary* curation — hence the independence problem.
HHS OCR is different: reporting a healthcare breach affecting 500+ individuals is **mandatory**,
so within that frame the list is close to a census. Inside a census frame you do not need
Chapman at all: the leak-site capture rate is directly measurable and its reciprocal is the
multiplier.

| HHS stratum | records | matched | leak-site capture | implied R | max possible capture |
|---|---:|---:|---:|---:|---:|
| All breach types | 6,801 | 211 | 3.1% | 32.2x | 15.5% |
| Hacking/IT incident | 4,390 | 201 | 4.6% | 21.8x | 24.1% |
| Ransomware-indicated | 1,226 | 52 | 4.2% | 23.6x | 86.2% |
| **Ransomware-indicated, 2019+** | **1,107** | **51** | **4.6%** | **21.7x** | **95.5%** |

The last row is the one to read: at 95.5% max-possible capture the two list sizes are comparable,
so the low capture rate is not an artifact of comparing a small list to a large one. Leak sites
appear to carry under 5% of mandatorily-reported large healthcare ransomware breaches.

**So which is right, 5-8x or 22x?** Neither cleanly, and the honest answer is to report both:

- Chapman on Comparitech is biased **down** by positive list dependence.
- The HHS capture rate is biased **down as a capture rate** — and so its reciprocal biased
  **up** — by frame mismatch: HHS has a 500+ individuals floor while healthcare's 693,801 firms
  are mostly small practices that could never qualify; HHS uses legal entity names
  (`Humana Inc`) where leak sites post brands and domains (`HUMANA.COM`); and the
  ransomware flag is keyword-derived from a web description that is missing for ~12% of rows.

The published schedule follows the **conservative** route, which means the rates in the table
above are more likely too low than too high. Treat 5-8x as a floor, and read the HHS route as
evidence that the *high* scenario is better supported than the central one — particularly for
healthcare, whose measured 5.9x is probably a substantial underestimate.

Two details worth repeating, because each one quietly corrupted this number before being caught:

- Matching `encrypt` in HHS descriptions inflated the ransomware count by 36%, because HIPAA
  narratives use encryption as *mitigation* language ("an employee sent an **unencrypted** email",
  "the stolen laptop was encrypted"). The flag now requires `ransom`, `extort` or a named strain.
- Strain names must be **word-bounded**. Unbounded, `conti` matched 90 descriptions through
  "**conti**nued" and `hive` matched 12 through "arc**hive**" — 102 spurious ransomware flags,
  which together with the `encrypt` problem had the count at 1,863 instead of the correct 1,246.

Both were found by a verification check rather than by reading the number and finding it plausible,
which is the only reason they were found at all: 1,863 looked entirely reasonable.

### Read the ranking, not the level

R multiplies every rate, so it moves the whole table up or down together and largely cancels out
of the *ordering*. This is checked rather than asserted: the industry ranking is **identical in
all 14 positions** between the observed and the fully-adjusted numerator, so the ordering is a
product of the data and not of the assumptions. The ordering is the defensible product; the
absolute level carries a multiplicative uncertainty of at least 2x (see the two routes above).
Specific warnings:

- **`Business Services` is not risk-homogeneous.** It spans five unrelated NAICS sectors and
  1.79M firms, including 366K micro-realtors and landlords. Its headline rate is close to
  meaningless; use the constituent NAICS codes instead.
- **`Public Sector` is counted in governments, not firms** (NAICS 92 is absent from SUSB
  entirely). One county is one unit but runs many separately attackable agencies. Never put this
  rate in an unlabelled column beside the firm-based ones.
- **This measures leak-site *listing* frequency, not attack frequency.** `attackdate` equals
  `discovered` for 65% of records, so the date is largely the posting date.
- **Band-level cells are much weaker than the industry marginals,** because the size curve is
  pooled across industries. Prefer the marginals.
- **The smallest band is the weakest point.** Firmographic labels come from ZoomInfo-style
  profiles, which are sparse below ~5-10 employees, so the 1-4 band (63% of all US firms) rests
  on 7 records and b = 0.85 is probably too steep.

### Two dimensions carried as flags, deliberately not as multipliers

`sensitive_information` + `regulatory_regimes` (HIPAA, GLBA/NYDFS 500, FERPA, PCI-DSS, CJIS,
DFARS/CMMC, NERC CIP, TSA SDs) and a `process_dependence_index` — the share of an industry's
hazard and exposure taxonomy falling in the operational-disruption families (Manufacturing 0.31,
Transportation 0.28, Energy 0.25 ... Technology 0.10, Financial 0.10, Education 0.09).

Both are segmentation, not coefficients. There is no evidence base for a frequency multiplier on
either, and process dependence is really a *severity* construct — multiplying it into frequency
would double-count it.

### Not in v1

A fitted Poisson/NB model with credibility weighting; an explorer view; non-US scope; severity
(loss given attack); per-victim firmographic enrichment of the 22,153 domains; rolling the 2022
denominators forward to 2025 (worth <5%, and downward).

### Live mode — the explorer reading from Atlas

`explorer.html` ships with a baked-in snapshot so it works when opened as a plain file. Served
by `scripts/server.js`, the Insights tab instead fetches **live** from Atlas and shows a
"live from Atlas" badge. A static file can't reach MongoDB directly, so this tiny read-only
server sits between them (Node's built-in http + the mongodb driver, no framework).

```bash
npm install                                  # the mongodb driver
export MONGODB_URI='mongodb+srv://...'        # same string as load_mongo.py
npm run serve                                 # -> http://localhost:8080
```

Read-only endpoints: `/api/health`, `/api/insights` (mapped to the chart shape), `/api/industries`,
`/api/synthesis`. The fetch is same-origin, so there's no CORS to configure. Opened as a file
with no server, the fetch simply fails and the snapshot stands — the self-contained file never
breaks. Refresh the data any time with `node scripts/export_mongo.js && python scripts/load_mongo.py`;
the page reflects it on next load.

**Design note — the denormalization line.** `incidents` are their own collection (updatable,
good for the archive role) but referenced from `industries` via `incident_ids`; the app joins
with a `$lookup`. Victims are separate because 27k is too much to embed. This keeps the app
fast, analytics flat, and the archive normalized — the three jobs a single store had to serve.

---

## Natural-language querying (GraphRAG)

Every question is answered by an LLM, but grounded in retrieved evidence — never the model's
memory. What gets retrieved depends on the question, so a router (`rag_core.py`) picks one of
three lanes:

| Lane | Example | Retrieval source |
|---|---|---|
| **Semantic** | *"why is healthcare targeted so heavily?"* | **Neo4j** vector search + 1-hop traversal. This is the GraphRAG lane. |
| **Relational** | *"what's exposed in healthcare but not manufacturing?"* | **Neo4j** graph traversal. Vectors can't do this; Cypher can. |
| **Analytical** | *"how many incidents disclose the ransom amount?"* | **MongoDB** — the materialized `insights` doc + a targeted aggregation. Numbers come from the DB, verbatim. |

The vector index lives in **Neo4j** (native, 5.11+), so semantic retrieval can vector-search
**then traverse** — the thing Atlas vector search alone can't do. Embeddings are a **local model**
(`all-MiniLM-L6-v2`, ~1,300 short texts, seconds on CPU, **no API**). The OpenAI/Anthropic call
is only the final synthesis, and answers cite the `[n]` snippets they used.

### The production API (`api.py`)

A FastAPI service — the productionized interface. One long-running process holds the Neo4j
driver, Mongo client and embedding model, and answers over HTTP:

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in NEO4J_*, MONGODB_URI, OPENAI_API_KEY

python scripts/embed_graph.py    # once: builds the Neo4j vector index
python scripts/api.py            # reads .env; serves on $PORT (default 8090)
# or: uvicorn scripts.api:app --host 0.0.0.0 --port 8080
```

`rag_core.py` auto-loads a repo-root `.env` (gitignored), so the API and CLI run with one
command instead of exported env vars. Use `bolt://` for a single local Neo4j instance —
`neo4j://` attempts cluster routing and fails.

```bash
curl -s localhost:8080/api/ask -H 'content-type: application/json' \
     -d '{"question":"why is healthcare targeted so heavily?"}' | jq
# -> { "lane": "semantic", "answer": "...[1][3]", "evidence": [ {type,score,text,linked}, ... ] }
```

Endpoints: `POST /api/ask`, `GET /api/insights` (live, incl. coverage), `/api/industries`,
`/api/synthesis`, `/api/health`, and `/` serves the explorer. Backends are **independently
optional**: with only Mongo the analytical lane still works; the graph lanes return a clear
503 until Neo4j is wired. So a missing backend degrades, never crashes.

### CLI (`ask.py`)

Same engine, terminal front end, for quick testing:

```bash
python scripts/ask.py "how many incidents disclose the ransom amount?"
python scripts/ask.py "what's exposed in healthcare but not manufacturing?"
python scripts/ask.py "why is healthcare unique?" --answer   # + LLM synthesis
```

Without `--answer` (or an API key) it prints the retrieved evidence only — no API call.

---

## How the research was run

One agent per industry, fanned out in parallel. Each agent:

1. Pulled its sector's victim list from the ransomware.live API
2. Cross-checked against RansomLook and ransomwatch
3. Selected 5–9 notable victims, weighted toward larger organisations, press-covered incidents, recent years, and geographic spread
4. Researched each one for real reported financial impact, ransom, downtime/recovery, and records affected — citing source URLs
5. Derived the industry-specific hazard and exposure taxonomy
6. Gathered industry-level aggregate statistics from Sophos *State of Ransomware*, Coveware Quarterly, IBM *Cost of a Data Breach*, Verizon DBIR, and Chainalysis

A final synthesis pass compared across industries and pulled global aggregate loss figures.

---

## Caveats worth knowing

- **Leak-site data undercounts.** These trackers record victims that groups *chose to publish*. Organisations that paid quietly, or were hit by groups that don't run leak sites, do not appear. Treat counts as a floor, not a total.
- **Sector tags are the tracker's, not a standard.** ransomware.live's `activity` field is mapped onto DBIR-style groupings here, but the underlying tagging is theirs and is occasionally inconsistent (`Consumer Services` vs `Consumer services` both appear upstream).
- **Financial figures are not like-for-like.** A "cost" figure may be a company's reported total incident cost, an insurance estimate, a regulatory fine, or an analyst estimate. The `source` column matters — check it before aggregating.
- **Blank ≠ zero.** An empty financial or ransom field means it wasn't publicly reported.

### Per-industry grounding — read before aggregating

Not every industry record rests on the same footing:

| Grounding | Industries |
|---|---|
| Pulled sector victim data from the ransomware.live API | 12 of 14 |
| Fell back to the public HTML activity page (`/activity/Energy`, 826 victims) | Energy and Utilities |
| **Base-data pull failed entirely** — incidents sourced from press/WebSearch only | **Public Administration (Government)** |

Public Administration's incidents are real and individually cited, but that record is **not** grounded in the leak-site database, so its victim counts and group rankings should not be treated as comparable to the others. Re-running it against `/v2/sectorvictims/Public%20Sector` with the corrected endpoint would fix this.

Sector-level *loss* figures across all industries rest largely on survey data (Sophos, IBM, Comparitech) rather than incident disclosure. In the Education pull, for example, only 13% of 1,296 records had a press link, 0.9% an explicit ransom figure, and 1.6% a data size; 27% had no country at all. Percentages in the overviews are stated against records with a resolved value, not the raw total.

- Four industry agents (Public Sector, Agriculture, Technology, Telecommunications) completed while the automated output classifier was unavailable, so their records did not receive that secondary review. Their sourcing is present and checkable in `sources.txt` — spot-check before relying on them for anything load-bearing.
