#!/usr/bin/env node
/**
 * build_dataset.js — assemble the final structured dataset.
 *
 * This is the script that actually produced data/industries.json and the CSVs.
 *
 * The research ran as a fan-out of one agent per industry. Each agent returned a
 * schema-validated JSON object. Those return values are recorded in the workflow
 * journal (journal.jsonl), one {"type":"result", ...} line per completed agent.
 *
 * Two complications this script exists to handle:
 *
 *   1. The run was interrupted twice by usage limits and had to be resumed, so
 *      the journal contains results from MULTIPLE runs. Some industries appear
 *      more than once; some appear only in one run. We take the UNION.
 *
 *   2. Agents named their industry inconsistently — the same sector came back as
 *      both "Agriculture, Forestry, Fishing and Food Production" and
 *      "Agriculture, Forestry, Fishing and Food Production (ransomware.live
 *      sector tag: ...)". We canonicalise the name and keep the RICHEST record
 *      (scored by how much research it actually contains).
 *
 * Usage:
 *   node build_dataset.js <journal.jsonl> [more-journals...]
 *   node build_dataset.js --from-dir ../data/agents   # dir of standalone .json files
 */

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.resolve(__dirname, '..', 'data');

/** Strip trailing parenthetical sector notes so duplicates collapse to one name. */
const canonicalName = (s) =>
  String(s || '')
    .replace(/\s*\(ransomware\.live sector[^)]*\)/i, '')
    .trim();

/** Rank records so the most thoroughly researched duplicate wins. */
const richness = (r) =>
  (r.example_incidents || []).length * 100 +
  (r.hazard_categories || []).length * 10 +
  (r.exposure_categories || []).length +
  (r.aggregate_stats || []).length;

/** CSV-quote a single field (RFC 4180: double the quotes, wrap in quotes). */
const q = (x) => '"' + (x == null ? '' : String(x)).replace(/"/g, '""') + '"';

const toCsv = (header, rows) => [header.join(','), ...rows.map((r) => r.map(q).join(','))].join('\n');

function loadFromJournals(files) {
  const out = [];
  for (const file of files) {
    if (!fs.existsSync(file)) {
      console.warn(`  skip (missing): ${file}`);
      continue;
    }
    const lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean);
    for (const line of lines) {
      let entry;
      try {
        entry = JSON.parse(line);
      } catch {
        continue; // tolerate partial/corrupt trailing lines
      }
      if (entry.type !== 'result') continue;
      let value = entry.value ?? entry.result ?? entry.output;
      try {
        const parsed = typeof value === 'string' ? JSON.parse(value) : value;
        if (parsed && parsed.industry) out.push(parsed);
      } catch {
        /* agent returned prose instead of JSON — ignore */
      }
    }
  }
  return out;
}

function loadFromDir(dir) {
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => {
      try {
        return JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
      } catch (e) {
        console.warn(`  skip (bad JSON): ${f} — ${e.message}`);
        return null;
      }
    })
    .filter((r) => r && r.industry);
}

/** Collapse duplicates by canonical industry name, keeping the richest record. */
function dedupe(records) {
  const best = new Map();
  for (const r of records) {
    const name = canonicalName(r.industry);
    r.industry = name;
    const current = best.get(name);
    if (!current || richness(r) > richness(current)) best.set(name, r);
  }
  return [...best.values()].sort((a, b) => a.industry.localeCompare(b.industry));
}

function build(industries) {
  fs.mkdirSync(DATA_DIR, { recursive: true });

  // Also fold in any standalone industry files written directly by an agent
  // (e.g. education.json, produced on a later recovery run).
  for (const extra of ['education.json']) {
    const p = path.join(DATA_DIR, extra);
    if (fs.existsSync(p)) {
      try {
        const rec = JSON.parse(fs.readFileSync(p, 'utf8'));
        if (rec && rec.industry && !industries.some((i) => canonicalName(i.industry) === canonicalName(rec.industry))) {
          industries.push(rec);
          console.log(`  folded in ${extra}`);
        }
      } catch (e) {
        console.warn(`  ${extra} is not valid JSON — ${e.message}`);
      }
    }
  }
  industries = dedupe(industries);

  fs.writeFileSync(path.join(DATA_DIR, 'industries.json'), JSON.stringify(industries, null, 2));

  // ---- incidents.csv : one row per researched real-world attack -------------
  const incidentRows = [];
  for (const ind of industries) {
    for (const e of ind.example_incidents || []) {
      incidentRows.push([
        ind.industry, e.victim, e.group, e.date, e.country,
        e.financial_impact, e.ransom_demanded_or_paid, e.downtime_and_recovery,
        e.data_impact, e.summary, (e.sources || []).join(' ; '),
      ]);
    }
  }
  fs.writeFileSync(
    path.join(DATA_DIR, 'incidents.csv'),
    toCsv(
      ['industry','victim','group','date','country','financial_impact','ransom_demanded_or_paid','downtime_and_recovery','data_impact','summary','sources'],
      incidentRows
    )
  );

  // ---- taxonomy.csv : hazards + exposures, long format ---------------------
  const taxRows = [];
  let hazards = 0, exposures = 0, subcats = 0;
  for (const ind of industries) {
    for (const h of ind.hazard_categories || []) {
      hazards++; subcats += (h.subcategories || []).length;
      taxRows.push([ind.industry, 'hazard', h.category, h.description, (h.subcategories || []).join(' | ')]);
    }
    for (const x of ind.exposure_categories || []) {
      exposures++; subcats += (x.subcategories || []).length;
      taxRows.push([ind.industry, 'exposure', x.category, x.description, (x.subcategories || []).join(' | ')]);
    }
  }
  fs.writeFileSync(
    path.join(DATA_DIR, 'taxonomy.csv'),
    toCsv(['industry', 'type', 'category', 'description', 'subcategories'], taxRows)
  );

  // ---- aggregate_stats.csv : sourced industry loss/frequency figures -------
  const statRows = [];
  for (const ind of industries) {
    for (const s of ind.aggregate_stats || []) {
      statRows.push([ind.industry, s.metric, s.value, s.source, s.source_url]);
    }
  }
  fs.writeFileSync(
    path.join(DATA_DIR, 'aggregate_stats.csv'),
    toCsv(['industry', 'metric', 'value', 'source', 'source_url'], statRows)
  );

  // ---- sources.txt : every distinct URL cited by an incident ---------------
  const sources = new Set();
  for (const ind of industries) {
    for (const e of ind.example_incidents || []) {
      for (const s of e.sources || []) sources.add(s);
    }
  }
  fs.writeFileSync(path.join(DATA_DIR, 'sources.txt'), [...sources].sort().join('\n'));

  console.log('\n=== dataset built ===');
  console.log(`industries        ${industries.length}`);
  console.log(`incidents         ${incidentRows.length}`);
  console.log(`hazard cats       ${hazards}`);
  console.log(`exposure cats     ${exposures}`);
  console.log(`subcategories     ${subcats}`);
  console.log(`aggregate stats   ${statRows.length}`);
  console.log(`unique sources    ${sources.size}`);
  for (const i of industries) {
    console.log(`  - ${i.industry} (${(i.example_incidents || []).length} incidents)`);
  }
}

function main() {
  const args = process.argv.slice(2);
  if (!args.length) {
    console.error('usage: node build_dataset.js <journal.jsonl>... | --from-dir <dir>');
    process.exit(1);
  }
  const records = args[0] === '--from-dir' ? loadFromDir(args[1]) : loadFromJournals(args);
  console.log(`loaded ${records.length} raw industry records`);
  build(records);
}

main();
