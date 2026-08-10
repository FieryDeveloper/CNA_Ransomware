#!/usr/bin/env node
/**
 * export_mongo.js — shape the dataset into the 6 MongoDB collections.
 *
 * All derivation logic (slugs, category families, dollar parsing, aggregation)
 * lives on the Node side so there is one implementation. This script emits plain
 * JSON arrays into data/mongo/; load_mongo.py only does I/O into Atlas. That
 * keeps the Python loader dumb and avoids two copies of the business rules.
 *
 * Collections (see README "MongoDB (Atlas)"):
 *   industries  14      curated taxonomy, one doc per industry
 *   incidents   107     researched incidents, normalized, with parsed $ figures
 *   victims     ~27k    the bulk leak-site scrape, flat
 *   taxonomy    ~136    deduped hazard/exposure categories across industries
 *   insights    1       materialized dashboard aggregates
 *   synthesis   1       cross-industry narrative + global stats
 *
 * Usage: node export_mongo.js
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const hash = (s) => crypto.createHash('sha1').update(String(s)).digest('hex').slice(0, 16);

const DATA = path.resolve(__dirname, '..', 'data');
const RAW = path.join(DATA, 'raw');
const OUT = path.join(DATA, 'mongo');
const NOW = new Date().toISOString();

const industries = JSON.parse(fs.readFileSync(path.join(DATA, 'industries.json'), 'utf8'));
const synthesis = fs.existsSync(path.join(DATA, 'synthesis.json'))
  ? JSON.parse(fs.readFileSync(path.join(DATA, 'synthesis.json'), 'utf8')) : {};

// --- shared helpers (mirror build_explorer.js / export_graph.js) -----------
const slug = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80);

const rawKey = (s) => String(s || '').toLowerCase().replace(/&/g, ' and ')
  .replace(/[\/\-–—_]+/g, ' ').replace(/[^a-z0-9 ]+/g, '').replace(/\s+/g, ' ').trim();
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
const norm = (s) => { const k = rawKey(s); return ALIASES.get(k) || k; };

const FAMILIES = [
  ['Third-Party & Supply Chain', /third party|supply chain|vendor|outsourc|msp|concentration/],
  ['Regulatory & Legal', /regulat|legal|complian|contractual|litigat|sanction|privacy law/],
  ['Insider & Workforce', /insider|workforce|human factor|credential|privileged access|student originated|social engineer/],
  ['Initial Access', /initial access|entry|intrusion|attack vector|exploitation/],
  ['Extortion & Impact', /extortion|ransom|leak|exfiltrat|double|encryption|impact tactic|harassment/],
  ['OT & Operational Disruption', /\bot\b|ics|scada|operational technology|physical|safety|production|availability|disruption|outage|network/],
  ['Data & IP Confidentiality', /confidential|intellectual property|trade secret|source code|data theft|sensitive data|pii|phi/],
  ['Business Interruption', /business interruption|project delay|revenue|financial loss|liquidity/],
];
const familyOf = (key) => (FAMILIES.find(([, re]) => re.test(key)) || ['Other'])[0];

// Guarded USD parser (mirrors build_explorer). Skips negations, caps non-loss
// outliers above $5B (ICBC's $62B Treasury-settlement volume).
const NEG = /^\s*(not\s+(a\s+)?(publicly\s+|single\s+)*disclos|no\s+(publicly\s+)?disclos|undisclosed|not\s+publicly\s+reported)/i;
function parseUSD(s) {
  if (!s || NEG.test(s)) return null;
  const m = String(s).match(/\$\s?([\d,]+(?:\.\d+)?)\s*(billion|bn|million|mn|m|k|thousand)?/i);
  if (!m) return null;
  let v = parseFloat(m[1].replace(/,/g, ''));
  const u = (m[2] || '').toLowerCase();
  if (/^b/.test(u)) v *= 1e9; else if (/^m/.test(u)) v *= 1e6; else if (/^k|thous/.test(u)) v *= 1e3;
  return v > 5e9 ? null : v;
}

const diffs = {};
for (const d of synthesis.industry_differentiators || []) diffs[norm(d.industry)] = d;

// --- load the bulk victim records -------------------------------------------
// Prefer the raw API pulls (data/raw/, gitignored, ~90MB). When those are absent
// (a fresh clone), fall back to the committed graph CSV, which carries the same
// 27k victims in a compact form. This is what lets the whole pipeline run from a
// clone without re-scraping, and keeps the 14MB victims JSON out of git.
// Full-text CSV parser (RFC 4180): quote-aware so a newline INSIDE a quoted
// field (some ransom notes have them) does not split the row.
function parseCsv(text) {
  const rows = []; let row = []; let cur = ''; let q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; }
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; }
    else if (c === '\r') { /* skip */ }
    else cur += c;
  }
  if (cur !== '' || row.length) { row.push(cur); rows.push(row); }
  return rows;
}
function loadBulk() {
  if (fs.existsSync(RAW)) {
    const files = fs.readdirSync(RAW).filter((x) => x.startsWith('sector_') && x.endsWith('.json'));
    if (files.length) {
      const recs = [];
      for (const f of files) {
        try {
          const arr = JSON.parse(fs.readFileSync(path.join(RAW, f), 'utf8').replace(/^﻿/, ''));
          if (Array.isArray(arr)) recs.push(...arr);
        } catch { /* skip */ }
      }
      if (recs.length) return { recs, source: 'data/raw' };
    }
  }
  // Fallback: data/graph/nodes_victim_bulk.csv
  const csv = path.join(DATA, 'graph', 'nodes_victim_bulk.csv');
  if (!fs.existsSync(csv)) return { recs: [], source: 'none' };
  const rows = parseCsv(fs.readFileSync(csv, 'utf8'));
  const hdr = rows[0];
  const col = (r, name) => r[hdr.indexOf(name)] || '';
  const recs = rows.slice(1).filter((r) => r.length > 1).map((r) => ({
    victim: col(r, 'victim'), activity: col(r, 'sector'), group: col(r, 'group'),
    country: col(r, 'country'), attackdate: col(r, 'attackdate'), discovered: col(r, 'discovered'),
    domain: col(r, 'domain'), data_size: col(r, 'data_size'),
    press: col(r, 'has_press') ? 'y' : '', ransom: col(r, 'ransom'), url: '', claim_url: '',
  }));
  return { recs, source: 'data/graph/nodes_victim_bulk.csv' };
}

// --- bulk scrape: per-sector summary + the flat victim docs -----------------
const secKey = (s) => String(s || '').trim().toLowerCase();
const bulkBySector = {};   // sector_key -> summary
const victims = [];
const sectorCasing = {};
{
  const { recs, source } = loadBulk();
  console.log(`bulk victims from ${source}: ${recs.length}`);
  {
    for (const v of recs) {
      if (!v || !v.victim) continue;
      const sk = secKey(v.activity || 'Unclassified');
      (sectorCasing[sk] ||= {})[v.activity || 'Unclassified'] = (sectorCasing[sk][v.activity || 'Unclassified'] || 0) + 1;
      const yr = String(v.attackdate || '').slice(0, 4);
      const s = (bulkBySector[sk] ||= { total: 0, years: {}, groups: {}, countries: {}, press: 0, ransom: 0 });
      s.total++;
      if (/^\d{4}$/.test(yr)) s.years[yr] = (s.years[yr] || 0) + 1;
      if (v.group) s.groups[v.group] = (s.groups[v.group] || 0) + 1;
      if (v.country) s.countries[v.country] = (s.countries[v.country] || 0) + 1;
      if (v.press) s.press++;
      if (v.ransom) s.ransom++;

      victims.push({
        // Prefer the ransomware.live URL (a stable natural key). Fall back to a
        // hash of the RAW fields, not slugs — non-Latin victim names slug to ''
        // and would otherwise collide into one _id, silently dropping victims.
        _id: v.url || ('rw-' + hash([v.victim, v.group, v.attackdate, v.domain, v.country].join('|'))),
        victim: v.victim,
        group: (v.group || '').trim() || null,
        sector_key: sk,
        sector: v.activity || 'Unclassified',
        country: (v.country || '').trim() || null,
        attackdate: v.attackdate || null,
        year: /^\d{4}$/.test(yr) ? Number(yr) : null,
        discovered: v.discovered || null,
        domain: v.domain || null,
        data_size: v.data_size || null,
        has_press: !!v.press,
        claim_url: v.claim_url || null,
        source: 'ransomware.live',
        ingested_at: NOW,
      });
    }
  }
}
const secDisplay = {};
for (const k of Object.keys(sectorCasing)) secDisplay[k] = Object.entries(sectorCasing[k]).sort((a, b) => b[1] - a[1])[0][0];
const topN = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n).map(([k, v]) => ({ name: k, n: v }));
const sectorOf = (ind) => {
  const sk = secKey(ind.ransomware_live_sector || '');
  return bulkBySector[sk] ? sk : null;
};

// --- collection: incidents --------------------------------------------------
const incidents = [];
for (const ind of industries) {
  for (const e of ind.example_incidents || []) {
    if (!e.victim) continue;
    incidents.push({
      _id: `${slug(ind.industry)}--${slug(e.victim)}`,
      industry_id: slug(ind.industry),
      industry: ind.industry,
      victim: e.victim,
      group: e.group || null,
      date: e.date || null,
      country: e.country || null,
      financial: { text: e.financial_impact || null, usd: parseUSD(e.financial_impact) },
      ransom: { text: e.ransom_demanded_or_paid || null, usd: parseUSD(e.ransom_demanded_or_paid) },
      downtime_and_recovery: e.downtime_and_recovery || null,
      data_impact: e.data_impact || null,
      summary: e.summary || null,
      sources: (e.sources || []).filter((u) => /^https?:/i.test(u)),
      updated_at: NOW,
    });
  }
}

// --- collection: industries -------------------------------------------------
const industryDocs = industries.map((ind) => {
  const d = diffs[norm(ind.industry)] || {};
  const sk = sectorOf(ind);
  const bs = sk ? bulkBySector[sk] : null;
  return {
    _id: slug(ind.industry),
    name: ind.industry,
    ransomware_live_sector: ind.ransomware_live_sector || null,
    overview: ind.overview || null,
    differentiators: {
      distinct: d.what_makes_it_distinct || null,
      extortion_leverage: d.primary_extortion_leverage || null,
      downtime_tolerance: d.downtime_tolerance || null,
    },
    hazards: (ind.hazard_categories || []).map((h) => ({
      category: h.category, family: familyOf(norm(h.category)),
      description: h.description || null, subcategories: h.subcategories || [],
    })),
    exposures: (ind.exposure_categories || []).map((e) => ({
      category: e.category, description: e.description || null, subcategories: e.subcategories || [],
    })),
    aggregate_stats: (ind.aggregate_stats || []).map((s) => ({
      metric: s.metric, value: s.value, source: s.source || null, source_url: s.source_url || null,
    })),
    incident_ids: incidents.filter((i) => i.industry_id === slug(ind.industry)).map((i) => i._id),
    bulk_summary: bs ? {
      total: bs.total,
      by_year: bs.years,
      top_groups: topN(bs.groups, 8),
      top_countries: topN(bs.countries, 6),
      press_pct: Math.round((bs.press / bs.total) * 100),
      ransom_pct: Math.round((bs.ransom / bs.total) * 100),
    } : null,
    updated_at: NOW,
  };
});

// --- collection: taxonomy (deduped categories across industries) ------------
function taxonomyDocs() {
  const out = [];
  for (const [field, type] of [['hazard_categories', 'hazard'], ['exposure_categories', 'exposure']]) {
    const idx = new Map();
    for (const ind of industries) {
      for (const c of ind[field] || []) {
        const k = norm(c.category);
        if (!k) continue;
        if (!idx.has(k)) idx.set(k, { _id: `${type}:${k}`, type, key: k, family: familyOf(k), description: '', industries: [], subcategory_count: 0 });
        const e = idx.get(k);
        if ((c.description || '').length > e.description.length) e.description = c.description || '';
        e.industries.push({ industry_id: slug(ind.industry), industry: ind.industry, label_as_reported: c.category, subcategories: c.subcategories || [] });
        e.subcategory_count += (c.subcategories || []).length;
      }
    }
    for (const e of idx.values()) { e.reach = e.industries.length; out.push(e); }
  }
  return out;
}

// --- collection: insights (materialized aggregates) -------------------------
function insightsDoc() {
  const bySector = {}, byYear = {}, byGroup = {}, byCountry = {}, gxs = {};
  for (const v of victims) {
    bySector[v.sector_key] = (bySector[v.sector_key] || 0) + 1;
    if (v.year) byYear[v.year] = (byYear[v.year] || 0) + 1;
    if (v.group) byGroup[v.group] = (byGroup[v.group] || 0) + 1;
    if (v.country) byCountry[v.country] = (byCountry[v.country] || 0) + 1;
    if (v.group) (gxs[v.group] ||= {})[v.sector_key] = (gxs[v.group][v.sector_key] || 0) + 1;
  }
  const sortDesc = (o) => Object.entries(o).sort((a, b) => b[1] - a[1]);
  const dedupe = (arr) => { const seen = new Set(); return arr.filter((x) => { const k = x.victim.split(' (')[0].trim().toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; }); };
  const fin = incidents.filter((i) => i.financial.usd).map((i) => ({ victim: i.victim, industry: i.industry, usd: i.financial.usd, text: i.financial.text })).sort((a, b) => b.usd - a.usd);
  const ran = incidents.filter((i) => i.ransom.usd).map((i) => ({ victim: i.victim, industry: i.industry, usd: i.ransom.usd, text: i.ransom.text })).sort((a, b) => b.usd - a.usd);
  const topGroups = sortDesc(byGroup).slice(0, 10).map(([g]) => g);
  const sectorKeys = sortDesc(bySector).map(([s]) => s);
  return {
    _id: 'current',
    generated_at: NOW,
    total_victims: victims.length,
    group_count: Object.keys(byGroup).length,
    country_count: Object.keys(byCountry).length,
    by_sector: sortDesc(bySector).map(([k, n]) => ({ sector: secDisplay[k] || k, n })),
    by_year: Object.keys(byYear).sort().map((y) => ({ year: Number(y), n: byYear[y] })),
    top_groups: sortDesc(byGroup).slice(0, 15).map(([group, n]) => ({ group, n })),
    top_countries: sortDesc(byCountry).slice(0, 12).map(([country, n]) => ({ country, n })),
    heatmap: { groups: topGroups, sectors: sectorKeys.map((k) => secDisplay[k] || k), cells: topGroups.map((g) => sectorKeys.map((s) => (gxs[g] && gxs[g][s]) || 0)) },
    costliest: dedupe(fin).slice(0, 15),
    largest_ransoms: dedupe(ran).slice(0, 15),
  };
}

// --- collection: synthesis --------------------------------------------------
const synthesisDoc = { _id: 'current', generated_at: NOW, ...synthesis };

// --- emit -------------------------------------------------------------------
fs.mkdirSync(OUT, { recursive: true });
const write = (name, docs) => {
  fs.writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify(docs, null, name === 'victims' ? 0 : 1));
  return Array.isArray(docs) ? docs.length : 1;
};
const counts = {
  industries: write('industries', industryDocs),
  incidents: write('incidents', incidents),
  victims: write('victims', victims),
  taxonomy: write('taxonomy', taxonomyDocs()),
  insights: write('insights', [insightsDoc()]),
  synthesis: write('synthesis', [synthesisDoc]),
};
console.log('exported to data/mongo/:');
for (const [k, v] of Object.entries(counts)) console.log(`  ${k.padEnd(12)} ${v}`);
