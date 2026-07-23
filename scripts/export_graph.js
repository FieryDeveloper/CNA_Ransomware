#!/usr/bin/env node
/**
 * export_graph.js — reshape the dataset into a knowledge graph.
 *
 * WHY A GRAPH: the interesting facts in this dataset are relationships, not
 * rows. "Which hazards recur across every industry?", "which groups span the
 * most sectors?", "what is exposed in healthcare that is not exposed in
 * manufacturing?" are all one hop or two in a graph and painful joins in CSV.
 *
 * KEY MODELLING DECISION: hazard and exposure categories are DEDUPLICATED by
 * normalised name across industries. That is what makes the graph informative —
 * when 14 industries all connect to a single "Initial Access Vectors" node, the
 * universality of that hazard becomes visible structurally instead of being
 * buried in 14 near-identical CSV rows. Subcategories stay per-category, since
 * those are where the industry-specific detail lives.
 *
 * Outputs (data/graph/):
 *   nodes_*.csv, rels_*.csv   neo4j-admin / LOAD CSV ready
 *   load.cypher               one-shot import script
 *   graph.json                {nodes, links} for the HTML explorer
 *
 * Usage: node export_graph.js
 */

const fs = require('fs');
const path = require('path');

const DATA = path.resolve(__dirname, '..', 'data');
const OUT = path.join(DATA, 'graph');
const RAW = path.join(DATA, 'raw');

const industries = JSON.parse(fs.readFileSync(path.join(DATA, 'industries.json'), 'utf8'));
const synthesis = fs.existsSync(path.join(DATA, 'synthesis.json'))
  ? JSON.parse(fs.readFileSync(path.join(DATA, 'synthesis.json'), 'utf8'))
  : null;

const q = (x) => '"' + (x == null ? '' : String(x)).replace(/"/g, '""') + '"';
const csv = (header, rows) => [header.join(','), ...rows.map((r) => r.map(q).join(','))].join('\n');

/** Normalise a category label so cosmetic variants collapse to one node:
 *    "Third-Party and Supply-Chain Risk"
 *    "Third-Party / Supply-Chain Risk"
 *    "Third-party & supply chain risk"      -> all one node
 *
 *  Only punctuation, casing and the &/and synonym are unified — never wording.
 *  "Insider and human-factor risk" and "Insider and workforce risk" stay
 *  separate, because those are genuinely different labels and merging them
 *  would fabricate agreement between industries that doesn't exist. */
const rawKey = (s) =>
  String(s || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[\/\-–—_]+/g, ' ')
    .replace(/[^a-z0-9 ]+/g, '')
    .replace(/\s+/g, ' ')
    .trim();

/** CURATED ALIASES — human-reviewed, deliberately explicit.
 *
 *  Agents independently produced labels that mean the same thing but differ in
 *  wording ("third party supply chain risk" vs "third party and supply chain
 *  risk"). String normalisation alone can't safely merge these, because '/'
 *  sometimes means "and" and sometimes means "or". Rather than guess with a
 *  looser regex, the collisions are listed here so the merge is auditable and
 *  anyone can disagree with a specific line.
 *
 *  Anything not listed stays separate. When in doubt, leave it out — a
 *  false merge invents cross-industry agreement that isn't in the data. */
const ALIASES = new Map(Object.entries({
  'third party supply chain risk': 'third party and supply chain risk',
  'third party and vendor risk': 'third party and supply chain risk',
  'supply chain and third party risk': 'third party and supply chain risk',
  'insider and workforce related risk': 'insider and workforce risk',
  'insider and human factor risk': 'insider and workforce risk',
  'insider human factor risk': 'insider and workforce risk',
  'regulatory and contractual exposure': 'regulatory and legal exposure',
  'regulatory legal and contractual exposure': 'regulatory and legal exposure',
  'regulatory compliance and legal exposure': 'regulatory and legal exposure',
  'initial access vector': 'initial access vectors',
  'extortion tactic': 'extortion tactics',
}));

const normKey = (s) => {
  const k = rawKey(s);
  return ALIASES.get(k) || k;
};

// ---------------------------------------------------------------------------
// Node/relationship accumulators
// ---------------------------------------------------------------------------
const nodes = { Industry: new Map(), Hazard: new Map(), Exposure: new Map(), Subcategory: new Map(),
                Incident: new Map(), Company: new Map(), Group: new Map(), Country: new Map(),
                Statistic: new Map(), Source: new Map(), Theme: new Map() };
const rels = [];

const addNode = (label, id, props = {}) => {
  if (!id) return null;
  if (!nodes[label].has(id)) nodes[label].set(id, { id, ...props });
  else Object.assign(nodes[label].get(id), props); // enrich on repeat
  return id;
};
const addRel = (from, fromLabel, type, to, toLabel, props = {}) => {
  if (from && to) rels.push({ from, fromLabel, type, to, toLabel, ...props });
};

// ---------------------------------------------------------------------------
// Build from the per-industry records
// ---------------------------------------------------------------------------
for (const ind of industries) {
  const iname = ind.industry;
  addNode('Industry', iname, {
    sector_tag: ind.ransomware_live_sector || '',
    overview: (ind.overview || '').slice(0, 1200),
    incident_count: (ind.example_incidents || []).length,
  });

  for (const [kind, label, relType] of [
    ['hazard_categories', 'Hazard', 'FACES'],
    ['exposure_categories', 'Exposure', 'EXPOSES'],
  ]) {
    for (const c of ind[kind] || []) {
      const key = normKey(c.category);
      if (!key) continue;
      addNode(label, key, { name: c.category, description: (c.description || '').slice(0, 800) });
      addRel(iname, 'Industry', relType, key, label);

      for (const sub of c.subcategories || []) {
        const subKey = `${key}::${normKey(sub)}`;
        addNode('Subcategory', subKey, { name: sub, parent: c.category, kind: label.toLowerCase() });
        addRel(key, label, 'INCLUDES', subKey, 'Subcategory');
      }
    }
  }

  for (const e of ind.example_incidents || []) {
    if (!e.victim) continue;
    const iid = `${iname}::${e.victim}`;
    addNode('Incident', iid, {
      victim: e.victim, date: e.date || '', country: e.country || '',
      financial_impact: (e.financial_impact || '').slice(0, 600),
      ransom: (e.ransom_demanded_or_paid || '').slice(0, 400),
      downtime: (e.downtime_and_recovery || '').slice(0, 600),
      data_impact: (e.data_impact || '').slice(0, 400),
      summary: (e.summary || '').slice(0, 900),
      source_count: (e.sources || []).length,
    });
    addRel(iname, 'Industry', 'HAD_INCIDENT', iid, 'Incident');

    addNode('Company', e.victim, {});
    addRel(iid, 'Incident', 'HIT', e.victim, 'Company');

    // A single incident may name several groups ("INC Ransom (Oct 2025); CoinbaseCartel (Apr 2026)")
    for (const g of String(e.group || '').split(/[;,/]|\band\b/)) {
      const name = g.replace(/\(.*?\)/g, '').trim();
      if (!name || name.length > 60) continue;
      addNode('Group', name, {});
      addRel(iid, 'Incident', 'PERPETRATED_BY', name, 'Group');
    }

    if (e.country) {
      const c = String(e.country).replace(/\(.*?\)/g, '').trim();
      if (c) { addNode('Country', c, {}); addRel(iid, 'Incident', 'OCCURRED_IN', c, 'Country'); }
    }

    for (const s of e.sources || []) {
      if (!/^https?:/i.test(s)) continue;
      let host = ''; try { host = new URL(s).hostname.replace(/^www\./, ''); } catch {}
      addNode('Source', s, { host });
      addRel(iid, 'Incident', 'CITED_BY', s, 'Source');
    }
  }

  for (const s of ind.aggregate_stats || []) {
    if (!s.metric) continue;
    const sid = `${iname}::${normKey(s.metric)}`;
    addNode('Statistic', sid, {
      metric: s.metric, value: (s.value || '').slice(0, 600),
      source: s.source || '', source_url: s.source_url || '', scope: 'industry',
    });
    addRel(iname, 'Industry', 'MEASURED_BY', sid, 'Statistic');
  }
}

// ---------------------------------------------------------------------------
// Cross-cutting themes + global statistics from the synthesis
// ---------------------------------------------------------------------------
if (synthesis) {
  for (const [arr, kind] of [
    [synthesis.common_hazard_themes || [], 'hazard'],
    [synthesis.common_exposure_themes || [], 'exposure'],
  ]) {
    for (const t of arr) {
      const key = normKey(t).slice(0, 120);
      if (key) addNode('Theme', key, { name: t, kind });
    }
  }
  for (const s of synthesis.global_aggregate_losses || []) {
    if (!s.metric) continue;
    addNode('Statistic', `GLOBAL::${normKey(s.metric)}`, {
      metric: s.metric, value: (s.value || '').slice(0, 800),
      source: s.source || '', source_url: s.source_url || '', scope: 'global',
    });
  }
  for (const d of synthesis.industry_differentiators || []) {
    const match = industries.find((i) => normKey(i.industry) === normKey(d.industry));
    if (match) {
      const n = nodes.Industry.get(match.industry);
      if (n) {
        n.distinct = (d.what_makes_it_distinct || '').slice(0, 700);
        n.extortion_leverage = (d.primary_extortion_leverage || '').slice(0, 500);
        n.downtime_tolerance = (d.downtime_tolerance || '').slice(0, 400);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Bulk leak-site victims from the raw API pulls (the "thousands" layer)
// ---------------------------------------------------------------------------
let bulkVictims = 0;
const bulkRows = [];
if (fs.existsSync(RAW)) {
  for (const file of fs.readdirSync(RAW).filter((f) => f.startsWith('sector_') && f.endsWith('.json'))) {
    let recs;
    try { recs = JSON.parse(fs.readFileSync(path.join(RAW, file), 'utf8-sig' in {} ? 'utf8' : 'utf8').replace(/^﻿/, '')); }
    catch { console.warn(`  skip unreadable ${file}`); continue; }
    if (!Array.isArray(recs)) continue;
    for (const v of recs) {
      if (!v || !v.victim) continue;
      bulkVictims++;
      bulkRows.push([
        v.victim, v.activity || '', v.group || '', v.country || '',
        (v.attackdate || '').slice(0, 10), (v.discovered || '').slice(0, 10),
        v.domain || '', v.data_size || '', v.press ? 'yes' : '', v.ransom || '',
      ]);
      if (v.group) addNode('Group', String(v.group).trim(), {});
    }
  }
}

// ---------------------------------------------------------------------------
// Emit
// ---------------------------------------------------------------------------
fs.mkdirSync(OUT, { recursive: true });

const NODE_FIELDS = {
  Industry: ['id', 'sector_tag', 'incident_count', 'overview', 'distinct', 'extortion_leverage', 'downtime_tolerance'],
  Hazard: ['id', 'name', 'description'],
  Exposure: ['id', 'name', 'description'],
  Subcategory: ['id', 'name', 'parent', 'kind'],
  Incident: ['id', 'victim', 'date', 'country', 'financial_impact', 'ransom', 'downtime', 'data_impact', 'summary', 'source_count'],
  Company: ['id'], Group: ['id'], Country: ['id'],
  Statistic: ['id', 'metric', 'value', 'source', 'source_url', 'scope'],
  Source: ['id', 'host'], Theme: ['id', 'name', 'kind'],
};

for (const [label, map] of Object.entries(nodes)) {
  const fields = NODE_FIELDS[label];
  const rows = [...map.values()].map((n) => fields.map((f) => n[f] ?? ''));
  fs.writeFileSync(path.join(OUT, `nodes_${label.toLowerCase()}.csv`), csv(fields, rows));
}

const byType = {};
for (const r of rels) (byType[r.type] ||= []).push(r);
for (const [type, list] of Object.entries(byType)) {
  fs.writeFileSync(
    path.join(OUT, `rels_${type.toLowerCase()}.csv`),
    csv(['from', 'from_label', 'to', 'to_label'], list.map((r) => [r.from, r.fromLabel, r.to, r.toLabel]))
  );
}

if (bulkRows.length) {
  fs.writeFileSync(
    path.join(OUT, 'nodes_victim_bulk.csv'),
    csv(['victim', 'sector', 'group', 'country', 'attackdate', 'discovered', 'domain', 'data_size', 'has_press', 'ransom'], bulkRows)
  );
}

// ---- graph.json for the HTML explorer -------------------------------------
// Incidents/sources/subcategories are omitted from the force layout by default
// (too many to render legibly) but kept as attached detail on their parents.
const jsonNodes = [];
const jsonLinks = [];
const pushN = (id, label, extra = {}) => jsonNodes.push({ id, label, ...extra });

for (const [label, map] of Object.entries(nodes)) {
  if (label === 'Source') continue;
  for (const n of map.values()) pushN(`${label}:${n.id}`, label, n);
}
for (const r of rels) {
  if (r.toLabel === 'Source') continue;
  jsonLinks.push({ source: `${r.fromLabel}:${r.from}`, target: `${r.toLabel}:${r.to}`, type: r.type });
}
fs.writeFileSync(path.join(OUT, 'graph.json'), JSON.stringify({ nodes: jsonNodes, links: jsonLinks }, null, 1));

// ---- Cypher loader ---------------------------------------------------------
const cypher = `// Ransomware Industry Knowledge Graph — Neo4j import
// Copy data/graph/*.csv into your Neo4j instance's import/ directory, then:
//   cat load.cypher | cypher-shell -u neo4j -p <password>
// Neo4j Desktop: right-click DB > Open folder > Import, then run this in Browser.

CREATE CONSTRAINT industry_id IF NOT EXISTS FOR (n:Industry) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT hazard_id IF NOT EXISTS FOR (n:Hazard) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT exposure_id IF NOT EXISTS FOR (n:Exposure) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT subcat_id IF NOT EXISTS FOR (n:Subcategory) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (n:Incident) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT company_id IF NOT EXISTS FOR (n:Company) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT group_id IF NOT EXISTS FOR (n:Group) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT country_id IF NOT EXISTS FOR (n:Country) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT stat_id IF NOT EXISTS FOR (n:Statistic) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT source_id IF NOT EXISTS FOR (n:Source) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT theme_id IF NOT EXISTS FOR (n:Theme) REQUIRE n.id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///nodes_industry.csv' AS r
MERGE (n:Industry {id: r.id})
SET n.sector_tag = r.sector_tag, n.incident_count = toInteger(r.incident_count),
    n.overview = r.overview, n.distinct = r.distinct,
    n.extortion_leverage = r.extortion_leverage, n.downtime_tolerance = r.downtime_tolerance;

LOAD CSV WITH HEADERS FROM 'file:///nodes_hazard.csv' AS r
MERGE (n:Hazard {id: r.id}) SET n.name = r.name, n.description = r.description;

LOAD CSV WITH HEADERS FROM 'file:///nodes_exposure.csv' AS r
MERGE (n:Exposure {id: r.id}) SET n.name = r.name, n.description = r.description;

LOAD CSV WITH HEADERS FROM 'file:///nodes_subcategory.csv' AS r
MERGE (n:Subcategory {id: r.id}) SET n.name = r.name, n.parent = r.parent, n.kind = r.kind;

LOAD CSV WITH HEADERS FROM 'file:///nodes_incident.csv' AS r
MERGE (n:Incident {id: r.id})
SET n.victim = r.victim, n.date = r.date, n.country = r.country,
    n.financial_impact = r.financial_impact, n.ransom = r.ransom,
    n.downtime = r.downtime, n.data_impact = r.data_impact,
    n.summary = r.summary, n.source_count = toInteger(r.source_count);

LOAD CSV WITH HEADERS FROM 'file:///nodes_company.csv' AS r MERGE (:Company {id: r.id});
LOAD CSV WITH HEADERS FROM 'file:///nodes_group.csv' AS r MERGE (:Group {id: r.id});
LOAD CSV WITH HEADERS FROM 'file:///nodes_country.csv' AS r MERGE (:Country {id: r.id});
LOAD CSV WITH HEADERS FROM 'file:///nodes_source.csv' AS r MERGE (n:Source {id: r.id}) SET n.host = r.host;
LOAD CSV WITH HEADERS FROM 'file:///nodes_theme.csv' AS r MERGE (n:Theme {id: r.id}) SET n.name = r.name, n.kind = r.kind;

LOAD CSV WITH HEADERS FROM 'file:///nodes_statistic.csv' AS r
MERGE (n:Statistic {id: r.id})
SET n.metric = r.metric, n.value = r.value, n.source = r.source,
    n.source_url = r.source_url, n.scope = r.scope;

LOAD CSV WITH HEADERS FROM 'file:///rels_faces.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Hazard {id: r.to}) MERGE (a)-[:FACES]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_exposes.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Exposure {id: r.to}) MERGE (a)-[:EXPOSES]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_includes.csv' AS r
MATCH (a {id: r.from}), (b:Subcategory {id: r.to}) MERGE (a)-[:INCLUDES]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_had_incident.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Incident {id: r.to}) MERGE (a)-[:HAD_INCIDENT]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_hit.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Company {id: r.to}) MERGE (a)-[:HIT]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_perpetrated_by.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Group {id: r.to}) MERGE (a)-[:PERPETRATED_BY]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_occurred_in.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Country {id: r.to}) MERGE (a)-[:OCCURRED_IN]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_cited_by.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Source {id: r.to}) MERGE (a)-[:CITED_BY]->(b);

LOAD CSV WITH HEADERS FROM 'file:///rels_measured_by.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Statistic {id: r.to}) MERGE (a)-[:MEASURED_BY]->(b);

// Bulk leak-site victims: the full ~27k scrape, not just the researched
// exemplars. Skip this block if you only want the curated layer.
// Batched so it does not build one huge transaction. Neo4j 5 syntax; on 4.x
// replace the CALL {} IN TRANSACTIONS wrapper with ':auto USING PERIODIC COMMIT 1000'.
CREATE INDEX victim_name IF NOT EXISTS FOR (n:Victim) ON (n.name);

LOAD CSV WITH HEADERS FROM 'file:///nodes_victim_bulk.csv' AS r
CALL {
  WITH r
  WITH r WHERE r.victim IS NOT NULL AND trim(r.victim) <> ''
  MERGE (v:Victim {name: r.victim, sector: r.sector})
    SET v.attackdate = r.attackdate, v.country = r.country,
        v.domain = r.domain, v.has_press = r.has_press
  // Guard: a blank group would otherwise MERGE an empty-id Group node.
  FOREACH (_ IN CASE WHEN r.group IS NOT NULL AND trim(r.group) <> '' THEN [1] ELSE [] END |
    MERGE (g:Group {id: r.group})
    MERGE (v)-[:ATTACKED_BY]->(g)
  )
} IN TRANSACTIONS OF 1000 ROWS;
`;
fs.writeFileSync(path.join(OUT, 'load.cypher'), cypher);

// ---- Neo4j Browser stylesheet (GraSS) --------------------------------------
// Drag this file onto the Neo4j Browser window, or run :style and paste it.
// Colours mirror explorer.html so the two read as one system: hazards warm,
// exposures cool, attackers plum, and size encodes level in the hierarchy.
fs.writeFileSync(path.join(OUT, 'style.grass'), `node {
  diameter: 50px;
  color: #A5ABB6;
  border-color: #9AA1AC;
  border-width: 2px;
  text-color-internal: #FFFFFF;
  font-size: 10px;
}
relationship {
  color: #C6CBD1;
  shaft-width: 1px;
  font-size: 8px;
  padding: 3px;
  text-color-external: #4A5158;
  text-color-internal: #FFFFFF;
  caption: '<type>';
}

/* Level 1 - the hubs you navigate from */
node.Industry {
  color: #2B3238; border-color: #11151A; diameter: 80px;
  text-color-internal: #FFFFFF; caption: '{id}'; font-size: 12px;
}

/* Level 2 - the two taxonomy axes. Warm = threat, cool = asset. */
node.Hazard {
  color: #A2432B; border-color: #7C3121; diameter: 65px;
  text-color-internal: #FFFFFF; caption: '{name}';
}
node.Exposure {
  color: #2A5578; border-color: #1D3D57; diameter: 65px;
  text-color-internal: #FFFFFF; caption: '{name}';
}

/* Level 3 - the specifics under each category */
node.Subcategory {
  color: #C9BDB6; border-color: #A99A91; diameter: 30px;
  text-color-internal: #2B3238; caption: '{name}';
}

/* The evidence layer */
node.Incident {
  color: #8A6023; border-color: #6A4919; diameter: 60px;
  text-color-internal: #FFFFFF; caption: '{victim}';
}
node.Company {
  color: #5A6268; border-color: #434A4F; diameter: 45px;
  text-color-internal: #FFFFFF; caption: '{id}';
}
node.Group {
  color: #6E3B5C; border-color: #532B45; diameter: 50px;
  text-color-internal: #FFFFFF; caption: '{id}';
}
node.Country {
  color: #3F6B5F; border-color: #2E5046; diameter: 40px;
  text-color-internal: #FFFFFF; caption: '{id}';
}
node.Statistic {
  color: #4A5A6B; border-color: #374553; diameter: 40px;
  text-color-internal: #FFFFFF; caption: '{metric}';
}
node.Source {
  color: #9AA1A7; border-color: #7C8288; diameter: 25px;
  text-color-internal: #FFFFFF; caption: '{host}';
}
node.Theme {
  color: #6B5E8B; border-color: #51476A; diameter: 40px;
  text-color-internal: #FFFFFF; caption: '{name}';
}

/* The bulk layer. Small on purpose - these come in thousands. */
node.Victim {
  color: #B0B6BA; border-color: #949A9E; diameter: 20px;
  text-color-internal: #2B3238; caption: '{name}';
}

/* Relationship colours follow their target */
relationship.FACES { color: #A2432B; shaft-width: 2px; }
relationship.EXPOSES { color: #2A5578; shaft-width: 2px; }
relationship.INCLUDES { color: #C9BDB6; }
relationship.HAD_INCIDENT { color: #8A6023; shaft-width: 2px; }
relationship.PERPETRATED_BY { color: #6E3B5C; shaft-width: 2px; }
relationship.ATTACKED_BY { color: #6E3B5C; }
relationship.HIT { color: #5A6268; }
relationship.OCCURRED_IN { color: #3F6B5F; }
relationship.MEASURED_BY { color: #4A5A6B; }
relationship.CITED_BY { color: #C6CBD1; }
`);

// ---- Example queries -------------------------------------------------------
fs.writeFileSync(path.join(OUT, 'queries.cypher'), `// ===========================================================================
// PART 1 - VISUAL queries. Run these in Neo4j Browser to SEE the graph.
// Browser only draws a picture when the query returns NODES, RELATIONSHIPS or
// PATHS. Returning scalars (counts, strings) gives you a table instead, which
// is why the analytical queries further down render as rows, not a diagram.
// ===========================================================================

// V1. The whole taxonomy skeleton: industries and the hazards they face.
//     Start here. ~14 industry nodes + 50 hazard nodes.
MATCH p = (:Industry)-[:FACES]->(:Hazard)
RETURN p;

// V2. One industry in full: its hazards, exposures and researched incidents.
MATCH p = (i:Industry)-[:FACES|EXPOSES|HAD_INCIDENT]->()
WHERE i.id = 'Healthcare and Social Assistance'
RETURN p;

// V3. Shared hazards between two industries - the overlap renders as a
//     bowtie, with the shared hazard nodes in the middle.
MATCH p = (a:Industry)-[:FACES]->(h:Hazard)<-[:FACES]-(b:Industry)
WHERE a.id = 'Energy and Utilities' AND b.id = 'Manufacturing'
RETURN p;

// V4. Cross-sector operators: groups that hit more than one industry.
//     Collect first, then re-match, so the picture stays readable.
MATCH (i:Industry)-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g:Group)
WITH g, count(DISTINCT i) AS reach WHERE reach > 1
MATCH p = (:Industry)-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g)
RETURN p;

// V5. One exposure family drilled to its specifics.
MATCH p = (:Industry)-[:EXPOSES]->(e:Exposure)-[:INCLUDES]->(:Subcategory)
WHERE e.name CONTAINS 'Operational Technology'
RETURN p;

// V6. Bulk layer: the busiest groups and a sample of their victims.
//     LIMIT matters here - 27k victim nodes will hang the browser.
MATCH (v:Victim)-[:ATTACKED_BY]->(g:Group)
WITH g, count(v) AS n ORDER BY n DESC LIMIT 5
MATCH p = (:Victim)-[:ATTACKED_BY]->(g)
RETURN p LIMIT 300;

// ===========================================================================
// PART 1b - READABLE EXAMPLES. Each returns a small subgraph you can read
// like a sentence. Start with S1; it is the clearest single picture in the DB.
// ===========================================================================

// S1. ONE INCIDENT, FULLY CONNECTED. The best "read the graph" example.
//     Renders as: Industry -> Incident -> {Company, Group, Country, Sources}
//     Reads as: "Healthcare had an incident at Change Healthcare, committed by
//     ALPHV/BlackCat, in the US, evidenced by these sources."
//     Swap the victim name for any other, e.g. 'MGM Resorts International'.
MATCH p = (i:Industry)-[:HAD_INCIDENT]->(n:Incident)-[]->()
WHERE n.victim STARTS WITH 'Change Healthcare'
RETURN p;

// S2. WHY THE TAXONOMY HAS TWO AXES. One industry, both axes, one hop.
//     The warm cluster is what happens TO you; the cool cluster is what you own.
MATCH p = (i:Industry)-[:FACES|EXPOSES]->()
WHERE i.id = 'Healthcare and Social Assistance'
RETURN p;

// S3. THE CENTRAL FINDING, AS A PICTURE.
//     Hazards shared by 10+ industries: a dense hub-and-spoke.
//     Contrast with S4 below, which is the same query for exposures.
MATCH (i:Industry)-[:FACES]->(h:Hazard)
WITH h, count(i) AS reach WHERE reach >= 10
MATCH p = (:Industry)-[:FACES]->(h)
RETURN p;

// S4. Same shape, exposures. Almost nothing comes back: exposures are
//     industry-specific. Run S3 and S4 back to back and the asymmetry is
//     obvious on screen. That is the project's headline in two queries.
MATCH (i:Industry)-[:EXPOSES]->(e:Exposure)
WITH e, count(i) AS reach WHERE reach >= 10
MATCH p = (:Industry)-[:EXPOSES]->(e)
RETURN p;

// S5. HOW ONE INDUSTRY DIFFERS. Manufacturing's exposures drilled to specifics.
//     You will see OT/ICS/SCADA and production systems, not patient records.
MATCH p = (i:Industry)-[:EXPOSES]->(:Exposure)-[:INCLUDES]->(:Subcategory)
WHERE i.id = 'Manufacturing'
RETURN p;

// S6. A GROUP'S FOOTPRINT. Which industries one actor reaches, with victims.
MATCH p = (:Industry)-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g:Group)
WHERE g.id CONTAINS 'LockBit'
RETURN p;

// S7. SUPPLY-CHAIN AGGREGATION. Incidents whose loss landed on somebody else.
//     CDK Global and Change Healthcare are the clearest cases.
MATCH p = (i:Industry)-[:HAD_INCIDENT]->(n:Incident)-[:PERPETRATED_BY]->(:Group)
WHERE n.summary CONTAINS 'third-party' OR n.summary CONTAINS 'supply chain'
   OR n.victim CONTAINS 'CDK' OR n.victim CONTAINS 'Change Healthcare'
RETURN p;

// S8. WHERE THE MONEY IS. Incidents with a disclosed dollar figure, by industry.
MATCH p = (i:Industry)-[:HAD_INCIDENT]->(n:Incident)
WHERE n.financial_impact CONTAINS '$'
RETURN p;

// ===========================================================================
// PART 2 - ANALYTICAL queries. These return tables, not diagrams.
// ===========================================================================


// 1. Which hazards are universal? (connected to the most industries)
MATCH (i:Industry)-[:FACES]->(h:Hazard)
RETURN h.name AS hazard, count(i) AS industries ORDER BY industries DESC;

// 2. What is exposed in Healthcare but NOT in Manufacturing?
MATCH (:Industry {id:'Healthcare and Social Assistance'})-[:EXPOSES]->(e:Exposure)
WHERE NOT EXISTS { MATCH (:Industry {id:'Manufacturing'})-[:EXPOSES]->(e) }
RETURN e.name, e.description;

// 3. Which groups attack the most industries? (cross-sector operators)
MATCH (i:Industry)-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g:Group)
RETURN g.id AS group, count(DISTINCT i) AS industries, count(*) AS incidents
ORDER BY industries DESC, incidents DESC LIMIT 20;

// 4. Costliest disclosed incidents
MATCH (i:Industry)-[:HAD_INCIDENT]->(n:Incident)
WHERE n.financial_impact CONTAINS '$'
RETURN i.id AS industry, n.victim, n.financial_impact, n.downtime LIMIT 25;

// 5. Two industries' shared hazards — where a control investment pays twice
MATCH (a:Industry {id:'Energy and Utilities'})-[:FACES]->(h:Hazard)<-[:FACES]-(b:Industry {id:'Manufacturing'})
RETURN h.name;

// 6. Full exposure inventory for one industry (the "what is exposed" question)
MATCH (:Industry {id:'Healthcare and Social Assistance'})-[:EXPOSES]->(e:Exposure)-[:INCLUDES]->(s:Subcategory)
RETURN e.name AS exposure, collect(s.name) AS specifics;

// 7. Bulk scrape: most active groups overall
MATCH (v:Victim)-[:ATTACKED_BY]->(g:Group)
RETURN g.id AS group, count(v) AS victims ORDER BY victims DESC LIMIT 25;

// 8. Bulk scrape: victims per sector per year
MATCH (v:Victim) WHERE v.attackdate <> ''
RETURN v.sector AS sector, left(v.attackdate,4) AS year, count(*) AS victims
ORDER BY sector, year;
`);

// ---- Report ---------------------------------------------------------------
console.log('=== knowledge graph exported ===');
let totalNodes = 0;
for (const [label, map] of Object.entries(nodes)) {
  if (map.size) { console.log(`  ${label.padEnd(12)} ${map.size}`); totalNodes += map.size; }
}
console.log(`  ${'—'.repeat(20)}`);
console.log(`  nodes        ${totalNodes}`);
console.log(`  rels         ${rels.length}`);
for (const [t, l] of Object.entries(byType)) console.log(`     ${t.padEnd(18)} ${l.length}`);
console.log(`  bulk victims ${bulkVictims} (separate Victim layer)`);
console.log(`\nwritten to ${OUT}`);
