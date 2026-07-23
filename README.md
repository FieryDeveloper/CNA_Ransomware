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
  graph/               knowledge-graph export: node/rel CSVs, load.cypher, queries.cypher

scripts/
  fetch_ransomware_live.py   pull victims from ransomware.live (by sector or by year)
  fetch_ransomlook.py        pull RansomLook / ransomwatch corroboration data
  build_dataset.js           assemble agent output into the final dataset
  validate.js                coverage + integrity checks on the built dataset
  export_graph.js            reshape into a knowledge graph (Neo4j + explorer feed)
  build_explorer.js          regenerate explorer.html with data inlined
```

## Two layers of data

Worth being precise about, because the numbers differ by two orders of magnitude:

| Layer | Size | What it is |
|---|---|---|
| **Bulk scrape** | **27,108 victims** across all 14 sectors, 2015–2026 | Every leak-site posting, sector-tagged. Names, groups, dates, countries — but almost no impact data (only ~13% carry a press link, ~1% a ransom figure). |
| **Researched incidents** | **107** | Hand-researched exemplars with financial loss, ransom, downtime and recovery, each cited. These are the ones where impact was publicly reported. |

The taxonomy is derived from both. Quote 27,108 for frequency and the 107 for severity — they are not interchangeable.

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
| Researched incidents | 107 |
| Hazard categories | 94 |
| Exposure categories | 90 |
| Taxonomy subcategories | 984 |
| Aggregate loss/frequency stats | 179 |
| Unique cited sources | 376 |

**Incident coverage** — every one of the 107 incidents carries at least one cited source URL. 89 (83%) have downtime/recovery detail, 48 (45%) have a financial-impact figure, 47 (44%) have a ransom figure. The rest are marked *"not publicly disclosed"*, which is a genuine public-reporting gap, not missing research. Agents were explicitly instructed never to estimate a figure they could not source.

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
| Incident | 107 | Theme | 25 |
| Company | 103 | **Victim** (bulk) | **27,108** |

Relationships: `FACES`, `EXPOSES`, `INCLUDES`, `HAD_INCIDENT`, `HIT`, `PERPETRATED_BY`,
`OCCURRED_IN`, `CITED_BY`, `MEASURED_BY`, `ATTACKED_BY`.

Hazard and exposure categories are **deduplicated by name across industries** — that is what
makes the graph informative. When 14 industries all connect to one `Initial Access Vectors`
node, the universality is visible structurally instead of being buried in 14 near-identical
rows. Subcategories stay per-category, since that is where industry-specific detail lives.

`build_dataset.js` handles two real complications from how this was produced: the research run was interrupted by usage limits and resumed, so results span **multiple runs** (it takes the union), and agents named the same sector inconsistently (it canonicalises names and keeps the **richest** duplicate).

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
