#!/usr/bin/env node
/**
 * build_explorer.js — generate a self-contained taxonomy explorer.
 *
 * Emits explorer.html with all data inlined: no server, no CDN, no build step.
 * Open the file or send it to someone and it works.
 *
 * Payload design: the bulk scrape (25k+ victims) is summarised to per-sector
 * aggregates rather than embedded raw — the explorer is for reading the
 * taxonomy, and 25k rows would bloat the file without being readable. The raw
 * records stay in data/raw/ and the graph CSVs for querying.
 *
 * Usage: node build_explorer.js
 */

const fs = require('fs');
const path = require('path');

const DATA = path.resolve(__dirname, '..', 'data');
const RAW = path.join(DATA, 'raw');
const industries = JSON.parse(fs.readFileSync(path.join(DATA, 'industries.json'), 'utf8'));
const synthesis = fs.existsSync(path.join(DATA, 'synthesis.json'))
  ? JSON.parse(fs.readFileSync(path.join(DATA, 'synthesis.json'), 'utf8'))
  : {};

// Mirrors export_graph.js so node identity is consistent across outputs.
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

/** FAMILY LAYER.
 *
 *  Agents produced many near-synonym labels for the same underlying risk —
 *  "Insider and Credential Risk", "Insider Identity and Privileged Access
 *  Risk", "Insider and Student Originated Threat" are three industries'
 *  wordings of one family. As raw labels they each read as 1/14, which makes a
 *  shared risk look industry-specific and defeats the comparison.
 *
 *  Rather than overwrite the reported label (which carries real industry
 *  flavour — the Education one really is about students), each category is
 *  ALSO tagged with a family. The matrix can then be read either way:
 *  by family for comparability, as-reported for fidelity. First match wins,
 *  so order matters — more specific patterns go first. */
const FAMILIES = [
  ['Third-Party & Supply Chain', /third party|supply chain|vendor|outsourc|msp|concentration/],
  ['Regulatory & Legal',         /regulat|legal|complian|contractual|litigat|sanction|privacy law/],
  ['Insider & Workforce',        /insider|workforce|human factor|credential|privileged access|student originated|social engineer/],
  ['Initial Access',             /initial access|entry|intrusion|attack vector|exploitation/],
  ['Extortion & Impact',         /extortion|ransom|leak|exfiltrat|double|encryption|impact tactic|harassment/],
  ['OT & Operational Disruption',/\bot\b|ics|scada|operational technology|physical|safety|production|availability|disruption|outage|network/],
  ['Data & IP Confidentiality',  /confidential|intellectual property|trade secret|source code|data theft|sensitive data|pii|phi/],
  ['Business Interruption',      /business interruption|project delay|revenue|financial loss|liquidity/],
];
const familyOf = (key) => (FAMILIES.find(([, re]) => re.test(key)) || ['Other'])[0];

// Title-case a canonical key back into a display label.
const label = (k) => k.replace(/\b(ot|it|pii|phi|ip|pos|iot)\b/g, (m) => m.toUpperCase())
  .replace(/\b[a-z]/g, (m) => m.toUpperCase())
  .replace(/\bAnd\b/g, 'and').replace(/\bOf\b/g, 'of').replace(/\bThe\b/g, 'the');

// ---------------------------------------------------------------------------
// Taxonomy indexes — category -> which industries have it, with per-industry
// subcategories preserved (the detail is where industries actually differ).
// ---------------------------------------------------------------------------
const buildIndex = (field) => {
  const idx = new Map();
  for (const ind of industries) {
    for (const c of ind[field] || []) {
      const k = norm(c.category);
      if (!k) continue;
      if (!idx.has(k)) idx.set(k, { key: k, name: label(k), fam: familyOf(k), desc: '', inds: {} });
      const e = idx.get(k);
      if ((c.description || '').length > e.desc.length) e.desc = c.description || '';
      e.inds[ind.industry] = { raw: c.category, subs: c.subcategories || [] };
    }
  }
  return [...idx.values()].sort((a, b) =>
    Object.keys(b.inds).length - Object.keys(a.inds).length || a.name.localeCompare(b.name));
};

const hazards = buildIndex('hazard_categories');
const exposures = buildIndex('exposure_categories');

// ---------------------------------------------------------------------------
// Bulk scrape aggregates
// ---------------------------------------------------------------------------
const bulk = {};
let bulkTotal = 0;
if (fs.existsSync(RAW)) {
  for (const f of fs.readdirSync(RAW).filter((x) => x.startsWith('sector_') && x.endsWith('.json'))) {
    let recs;
    try { recs = JSON.parse(fs.readFileSync(path.join(RAW, f), 'utf8').replace(/^﻿/, '')); }
    catch { continue; }
    if (!Array.isArray(recs) || !recs.length) continue;
    const sector = recs[0].activity || f.slice(7, -5);
    const years = {}, groups = {}, countries = {};
    let press = 0, ransom = 0;
    for (const v of recs) {
      const y = String(v.attackdate || '').slice(0, 4);
      if (/^\d{4}$/.test(y)) years[y] = (years[y] || 0) + 1;
      if (v.group) groups[v.group] = (groups[v.group] || 0) + 1;
      if (v.country) countries[v.country] = (countries[v.country] || 0) + 1;
      if (v.press) press++;
      if (v.ransom) ransom++;
    }
    const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
    bulk[sector] = {
      total: recs.length, years,
      groups: top(groups, 8), countries: top(countries, 6),
      pressPct: Math.round((press / recs.length) * 100),
      ransomPct: Math.round((ransom / recs.length) * 100),
    };
    bulkTotal += recs.length;
  }
}

// Map DBIR industry names -> ransomware.live sector tags for the bulk join.
const sectorOf = (ind) => {
  const tag = (ind.ransomware_live_sector || '').trim();
  if (tag && bulk[tag]) return tag;
  const guess = Object.keys(bulk).find((s) => norm(s) === norm(tag));
  return guess || null;
};

/** The research prose is dense with em dashes. They read as a tic on screen,
 *  so they are converted to ordinary punctuation for display only: the source
 *  text in data/industries.json is never modified. A parenthetical pair
 *  ("X — like this — Y") becomes commas; a single dash becomes a comma, or a
 *  colon when what follows is a list or an explanation. Doubled punctuation
 *  left behind by the substitution is repaired afterwards. */
function deDash(s) {
  if (typeof s !== 'string' || s.indexOf('—') === -1) return s;
  return s
    .replace(/\s*—\s*/g, ', ')
    .replace(/,\s*,+/g, ', ')      // collapse runs
    .replace(/([,;:])\s*,/g, '$1 ') // ", ," and "; ,"
    .replace(/\s+,/g, ',')
    .replace(/,(\s*[.)\]])/g, '$1') // trailing comma before . ) ]
    .replace(/\s{2,}/g, ' ')
    .trim();
}
/** Walk the payload and clean every display string. URLs are left alone. */
function clean(v) {
  if (typeof v === 'string') return /^https?:\/\//i.test(v) ? v : deDash(v);
  if (Array.isArray(v)) return v.map(clean);
  if (v && typeof v === 'object') {
    const o = {};
    for (const [k, x] of Object.entries(v)) o[k] = (k === 'u' || k === 'source_url' || k === 'src') ? x : clean(x);
    return o;
  }
  return v;
}

// ---------------------------------------------------------------------------
// Payload
// ---------------------------------------------------------------------------
const diffs = {};
for (const d of synthesis.industry_differentiators || []) diffs[norm(d.industry)] = d;

const payload = {
  meta: {
    industries: industries.length,
    incidents: industries.reduce((n, i) => n + (i.example_incidents || []).length, 0),
    hazards: hazards.length,
    exposures: exposures.length,
    subcats: industries.reduce((n, i) =>
      n + (i.hazard_categories || []).reduce((m, c) => m + (c.subcategories || []).length, 0)
        + (i.exposure_categories || []).reduce((m, c) => m + (c.subcategories || []).length, 0), 0),
    stats: industries.reduce((n, i) => n + (i.aggregate_stats || []).length, 0),
    bulkTotal,
    generated: new Date().toISOString().slice(0, 10),
  },
  industries: industries.map((i) => {
    const d = diffs[norm(i.industry)] || {};
    const sec = sectorOf(i);
    return {
      name: i.industry,
      tag: i.ransomware_live_sector || '',
      overview: i.overview || '',
      distinct: d.what_makes_it_distinct || '',
      leverage: d.primary_extortion_leverage || '',
      tolerance: d.downtime_tolerance || '',
      bulk: sec ? bulk[sec] : null,
      incidents: (i.example_incidents || []).map((e) => ({
        v: e.victim, g: e.group || '', d: e.date || '', c: e.country || '',
        fin: e.financial_impact || '', ran: e.ransom_demanded_or_paid || '',
        dt: e.downtime_and_recovery || '', di: e.data_impact || '',
        s: e.summary || '', src: (e.sources || []).filter((u) => /^https?:/.test(u)),
      })),
      stats: (i.aggregate_stats || []).map((s) => ({
        m: s.metric, v: s.value, s: s.source || '', u: s.source_url || '',
      })),
    };
  }),
  hazards, exposures,
  global: (synthesis.global_aggregate_losses || []).map((s) => ({
    m: s.metric, v: s.value, s: s.source || '', u: s.source_url || '',
  })),
  comparison: synthesis.cross_industry_comparison || '',
  takeaways: synthesis.key_takeaways || [],
  highest: synthesis.highest_risk_industries || [],
};

// ---------------------------------------------------------------------------
// HTML
// ---------------------------------------------------------------------------
const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ransomware Risk Taxonomy Explorer</title>
<style>
/* Palette: chrome is neutral graphite so the only two chromatic elements on the
   page are the data hues. Hazard warm, exposure cool, and deliberately red vs
   blue rather than red vs green so the matrix survives deuteranopia. */
:root{
  --ground:#F4F3F0; --surface:#FCFBF9; --surface-2:#EFEEEA;
  --ink:#191C1F; --muted:#5A6268; --faint:#8B9298;
  --line:#DEDCD6; --line-strong:#BFBCB4;
  --accent:#2B3238; --accent-ink:#FCFBF9;
  --hazard:#A2432B; --hazard-soft:#EFE1DB;
  --exposure:#2A5578; --exposure-soft:#DDE4EC;
}
@media (prefers-color-scheme:dark){
  :root{
    --ground:#101315; --surface:#171A1D; --surface-2:#1E2226;
    --ink:#E4E5E2; --muted:#9AA1A7; --faint:#6C737A;
    --line:#282D32; --line-strong:#3C434A;
    --accent:#D6D8D4; --accent-ink:#171A1D;
    --hazard:#C9714F; --hazard-soft:#2A1B15;
    --exposure:#7BA5CA; --exposure-soft:#161F29;
  }
}
:root[data-theme="dark"]{
  --ground:#101315; --surface:#171A1D; --surface-2:#1E2226;
  --ink:#E4E5E2; --muted:#9AA1A7; --faint:#6C737A;
  --line:#282D32; --line-strong:#3C434A;
  --accent:#D6D8D4; --accent-ink:#171A1D;
  --hazard:#C9714F; --hazard-soft:#2A1B15;
  --exposure:#7BA5CA; --exposure-soft:#161F29;
}
:root[data-theme="light"]{
  --ground:#F4F3F0; --surface:#FCFBF9; --surface-2:#EFEEEA;
  --ink:#191C1F; --muted:#5A6268; --faint:#8B9298;
  --line:#DEDCD6; --line-strong:#BFBCB4;
  --accent:#2B3238; --accent-ink:#FCFBF9;
  --hazard:#A2432B; --hazard-soft:#EFE1DB;
  --exposure:#2A5578; --exposure-soft:#DDE4EC;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--ground); color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;
}
h1,h2,h3{font-family:Georgia,"Iowan Old Style","Times New Roman",serif;font-weight:600;text-wrap:balance;margin:0}
.mono{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-variant-numeric:tabular-nums}

header{border-bottom:1px solid var(--line-strong);background:var(--surface);position:sticky;top:0;z-index:20}
.hwrap{max-width:1560px;margin:0 auto;padding:13px 22px;display:flex;gap:22px;align-items:baseline;flex-wrap:wrap}
h1{font-size:17.5px;letter-spacing:-.005em}
.sub{color:var(--muted);font-size:12.5px}
.metrics{margin-left:auto;display:flex;gap:0;flex-wrap:wrap;align-items:stretch}
.metric{text-align:right;padding:0 15px;border-left:1px solid var(--line)}
.metric:first-child{border-left:0}
.metric b{display:block;font-size:14.5px;font-family:ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums;font-weight:600}
.metric span{font-size:10.5px;color:var(--faint)}

nav{max-width:1560px;margin:0 auto;padding:0 22px;display:flex;gap:0;border-bottom:1px solid var(--line)}
nav button{
  font:inherit;font-size:13px;background:none;border:0;color:var(--muted);cursor:pointer;
  padding:9px 15px;border-bottom:2px solid transparent;margin-bottom:-1px;
}
nav button:hover{color:var(--ink)}
nav button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--ink);font-weight:600}
nav button:focus-visible{outline:1px solid var(--ink);outline-offset:-3px}

main{max-width:1560px;margin:0 auto;padding:18px 22px 40px}
.panel{display:none}
.panel.on{display:block}

.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
input[type=search]{
  font:inherit;font-size:13px;padding:6px 10px;border:1px solid var(--line-strong);
  border-radius:3px;background:var(--surface);color:var(--ink);min-width:260px;
}
input[type=search]:focus{outline:1px solid var(--ink);outline-offset:0;border-color:var(--ink)}
.legend{display:flex;gap:16px;font-size:12px;color:var(--muted);align-items:center}
.seg{display:inline-flex;border:1px solid var(--line-strong);border-radius:3px;overflow:hidden}
.seg button{font:inherit;font-size:12.5px;padding:6px 13px;background:var(--surface);color:var(--muted);border:0;cursor:pointer}
.seg button+button{border-left:1px solid var(--line-strong)}
.seg button[aria-pressed="true"]{background:var(--accent);color:var(--accent-ink);font-weight:600}
.seg button:focus-visible{outline:1px solid var(--ink);outline-offset:-3px}
.famrow th{font-family:Georgia,serif!important;font-size:11.5px!important;color:var(--ink)!important;background:var(--surface-2)!important;letter-spacing:.03em}
.dot{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:middle}
.dot.h{background:var(--hazard)} .dot.e{background:var(--exposure)}

/* ---- matrix ---- */
.mwrap{overflow-x:auto;border:1px solid var(--line-strong);border-radius:3px;background:var(--surface)}
table{border-collapse:separate;border-spacing:0;font-size:12.5px;width:100%}
th,td{padding:0;text-align:left}
thead th{
  position:sticky;top:0;background:var(--surface);z-index:3;
  border-bottom:1px solid var(--line-strong);vertical-align:bottom;
  padding:8px 6px;font-weight:600;font-size:11px;color:var(--muted);
}
thead th.rot{height:132px;white-space:nowrap;width:26px;min-width:26px}
thead th.rot>div{transform:rotate(-90deg);transform-origin:left bottom;width:22px;margin-left:50%}
tbody th{
  position:sticky;left:0;background:var(--surface);z-index:2;
  padding:7px 12px 7px 14px;font-weight:500;font-size:12.5px;
  border-bottom:1px solid var(--line);border-right:1px solid var(--line-strong);
  white-space:nowrap;max-width:290px;overflow:hidden;text-overflow:ellipsis;
}
tbody tr:hover th,tbody tr:hover td{background:var(--surface-2)}
tbody td{border-bottom:1px solid var(--line);text-align:center;width:26px}
.cell{width:14px;height:14px;border-radius:2px;display:inline-block;cursor:pointer;border:0;padding:0}
.cell:focus-visible{outline:1px solid var(--ink);outline-offset:2px}
.cell.h{background:var(--hazard)} .cell.e{background:var(--exposure)}
.cell.off{background:var(--line);opacity:.6}
.reach{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--faint);padding-right:10px;text-align:right;width:44px}

/* ---- cards / lists ---- */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1px;background:var(--line);border:1px solid var(--line-strong);border-radius:3px}
.card{background:var(--surface);padding:13px 15px}
.card h3{font-size:14.5px;margin-bottom:4px;line-height:1.3}
.card .meta{font-size:11.5px;color:var(--faint);margin-bottom:7px;font-family:ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
.card p{margin:0 0 8px;color:var(--muted);font-size:13px}
.tag{
  display:inline-block;font-size:11px;padding:1px 6px;border-radius:2px;
  border:1px solid var(--line-strong);color:var(--muted);margin:2px 3px 2px 0;
}
.tag.h{border-color:var(--hazard);color:var(--hazard);background:var(--hazard-soft)}
.tag.e{border-color:var(--exposure);color:var(--exposure);background:var(--exposure-soft)}
.clickable{cursor:pointer}
.clickable:hover{background:var(--surface-2)}
.clickable:focus-visible{outline:1px solid var(--ink);outline-offset:-2px}

/* ---- detail drawer ---- */
.scrim{position:fixed;inset:0;background:rgba(10,14,18,.4);opacity:0;pointer-events:none;transition:opacity .18s;z-index:40}
.scrim.on{opacity:1;pointer-events:auto}
aside{
  position:fixed;top:0;right:0;height:100%;width:min(560px,92vw);z-index:50;
  background:var(--surface);border-left:1px solid var(--line-strong);
  transform:translateX(100%);transition:transform .22s ease;
  overflow-y:auto;padding:22px 24px 60px;
}
aside.on{transform:none}
aside h2{font-size:18.5px;margin-bottom:4px}
aside .kicker{font-size:11.5px;color:var(--faint);margin-bottom:9px;font-family:ui-monospace,Consolas,monospace}
aside h4{font-size:12px;color:var(--ink);margin:19px 0 6px;font-family:Georgia,serif;font-weight:600;padding-bottom:4px;border-bottom:1px solid var(--line)}
aside p{font-size:13.5px;line-height:1.6;color:var(--muted);margin:0 0 10px}
aside ul{margin:0;padding-left:17px;font-size:13px;color:var(--muted);line-height:1.6}
aside li{margin-bottom:4px}
.close{position:absolute;top:14px;right:16px;background:none;border:0;font-size:22px;color:var(--muted);cursor:pointer;line-height:1;padding:4px 8px;border-radius:4px}
.close:hover{color:var(--ink);background:var(--surface-2)}
.close:focus-visible{outline:2px solid var(--accent)}
.inc{border-left:2px solid var(--line-strong);padding:2px 0 2px 12px;margin-bottom:14px}
.inc b{font-size:13.5px}
.inc .f{font-size:12.5px;color:var(--muted);margin-top:3px}
.inc .f i{font-style:normal;color:var(--faint);font-size:11.5px;margin-right:6px;display:inline-block;min-width:66px;font-family:ui-monospace,Consolas,monospace}
.nd{color:var(--faint);font-style:italic}
a{color:var(--accent)}
.srcs{font-size:11px;word-break:break-all}
.srcs a{margin-right:8px}

/* ---- bulk bars ---- */
.years{display:flex;align-items:flex-end;gap:3px;height:60px;margin:8px 0}
.years div{flex:1;background:var(--accent);opacity:.75;border-radius:2px 2px 0 0;min-height:2px}
.years div:hover{opacity:1}
.ylab{display:flex;gap:3px;font-size:9px;color:var(--faint);font-family:ui-monospace,Consolas,monospace}
.ylab span{flex:1;text-align:center}

.note{font-size:12px;color:var(--faint);margin-top:14px;line-height:1.6;max-width:80ch}
.prose{max-width:76ch}
.prose p{color:var(--muted);font-size:14px;line-height:1.65;margin:0 0 13px}
.prose h3{font-size:15px;margin:22px 0 8px}
.statrow{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid var(--line);font-size:13px}
.statrow .v{font-family:ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums;color:var(--ink);flex:0 0 auto}
.statrow .m{color:var(--muted);flex:1}
.statrow .s{color:var(--faint);font-size:11px;flex:0 0 auto;text-align:right;max-width:190px}
@media (max-width:720px){
  .metrics{width:100%;margin-left:0;justify-content:flex-start;gap:14px}
  .metric{text-align:left}
  .statrow{flex-wrap:wrap}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style>
</head>
<body>
<header>
  <div class="hwrap">
    <div>
      <h1>Ransomware Risk Taxonomy</h1>
      <div class="sub">Hazards, exposures and researched losses across __IND__ industries</div>
    </div>
    <div class="metrics" id="metrics"></div>
  </div>
</header>
<nav id="nav" role="tablist"></nav>
<main>
  <section class="panel on" id="p-matrix" role="tabpanel">
    <div class="bar">
      <div class="seg" role="group" aria-label="Grouping">
        <button id="bFam" aria-pressed="true">By family</button><button id="bRaw" aria-pressed="false">As reported</button>
      </div>
      <div class="legend">
        <span><span class="dot h"></span>Hazard: what happens to you</span>
        <span><span class="dot e"></span>Exposure: what you own that gets hit</span>
      </div>
    </div>
    <div class="mwrap"><table id="matrix"></table></div>
    <p class="note" id="mnote"></p>
  </section>

  <section class="panel" id="p-ind" role="tabpanel">
    <div class="bar"><input type="search" id="qi" placeholder="Filter industries…" aria-label="Filter industries"></div>
    <div class="grid" id="inds"></div>
  </section>

  <section class="panel" id="p-cat" role="tabpanel">
    <div class="bar">
      <input type="search" id="qc" placeholder="Search categories and subcategories…" aria-label="Search categories">
      <div class="legend"><span><span class="dot h"></span>Hazards</span><span><span class="dot e"></span>Exposures</span></div>
    </div>
    <div class="grid" id="cats"></div>
  </section>

  <section class="panel" id="p-inc" role="tabpanel">
    <div class="bar"><input type="search" id="qn" placeholder="Search victims, groups, impacts…" aria-label="Search incidents"></div>
    <div class="grid" id="incs"></div>
  </section>

  <section class="panel" id="p-syn" role="tabpanel">
    <div class="prose" id="syn"></div>
  </section>
</main>

<div class="scrim" id="scrim"></div>
<aside id="drawer" aria-hidden="true" role="dialog" aria-label="Detail"><button class="close" id="closeBtn" aria-label="Close">&times;</button><div id="dbody"></div></aside>

<script>
const D = __DATA__;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ND = /^(not (publicly )?(disclosed|reported|available|known)|unknown|undisclosed|n\\/a)/i;
const fmt = (v) => !v ? '<span class="nd">not recorded</span>' : (ND.test(v) ? '<span class="nd">' + esc(v) + '</span>' : esc(v));
const num = (n) => n.toLocaleString('en-US');

/* metrics strip */
$('#metrics').innerHTML = [
  [num(D.meta.bulkTotal), 'victims scraped'],
  [D.meta.incidents, 'researched'],
  [D.meta.hazards, 'hazards'],
  [D.meta.exposures, 'exposures'],
  [num(D.meta.subcats), 'subcategories'],
].map(([b, s]) => '<div class="metric"><b>' + b + '</b><span>' + s + '</span></div>').join('');

/* tabs */
const TABS = [['matrix','Matrix'],['ind','Industries'],['cat','Categories'],['inc','Incidents'],['syn','Cross-industry']];
$('#nav').innerHTML = TABS.map(([id,t],i) =>
  '<button role="tab" data-t="'+id+'" aria-selected="'+(i===0)+'">'+t+'</button>').join('');
$('#nav').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-t]'); if (!b) return;
  document.querySelectorAll('#nav button').forEach((x) => x.setAttribute('aria-selected', x === b));
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('on', p.id === 'p' + '-' + b.dataset.t));
});

/* ---------- drawer ---------- */
const drawer = $('#drawer'), scrim = $('#scrim');
let lastFocus = null;
function open(html) {
  lastFocus = document.activeElement;
  $('#dbody').innerHTML = html;
  drawer.classList.add('on'); scrim.classList.add('on');
  drawer.setAttribute('aria-hidden', 'false');
  drawer.scrollTop = 0; $('#closeBtn').focus();
}
function close() {
  drawer.classList.remove('on'); scrim.classList.remove('on');
  drawer.setAttribute('aria-hidden', 'true');
  if (lastFocus) lastFocus.focus();
}
$('#closeBtn').onclick = close; scrim.onclick = close;
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && drawer.classList.contains('on')) close(); });

/* ---------- matrix ---------- */
const INDS = D.industries.map((i) => i.name);
const short = (n) => n.replace(/ and .*/, '').replace(/,.*/, '').slice(0, 22);
let MODE = 'fam';
/** Collapse categories into families: a family is "present" in an industry if
 *  any of its member categories is. Keeps member categories for the drawer. */
function byFamily(list) {
  const m = new Map();
  for (const c of list) {
    if (!m.has(c.fam)) m.set(c.fam, { key: 'fam:' + c.fam, name: c.fam, fam: c.fam, desc: '', inds: {}, members: [] });
    const f = m.get(c.fam);
    f.members.push(c);
    for (const i of Object.keys(c.inds)) {
      if (!f.inds[i]) f.inds[i] = { raw: [], subs: [] };
      f.inds[i].raw.push(c.inds[i].raw);
      f.inds[i].subs.push(...c.inds[i].subs);
    }
  }
  return [...m.values()].sort((a, b) => Object.keys(b.inds).length - Object.keys(a.inds).length);
}

function buildMatrix() {
  const rows = [];
  const section = (list, kind) => {
    rows.push('<tr class="famrow"><th colspan="' + (INDS.length + 2) + '" style="color:var(--' + (kind === 'h' ? 'hazard' : 'exposure') + ')!important;letter-spacing:.04em;text-transform:uppercase">'
      + (kind === 'h' ? 'Hazards' : 'Exposures') + ' · ' + list.length + '</th></tr>');
    for (const c of list) {
      const n = Object.keys(c.inds).length;
      rows.push('<tr><th title="' + esc(c.name) + (c.members ? ', ' + c.members.length + ' reported labels' : '') + '">' + esc(c.name)
        + (c.members && c.members.length > 1 ? ' <span style="color:var(--faint);font-weight:400">(' + c.members.length + ')</span>' : '')
        + '</th><td class="reach">' + n + '/' + INDS.length + '</td>'
        + INDS.map((i) => {
            const on = !!c.inds[i];
            return '<td>' + (on
              ? '<button class="cell ' + kind + '" data-c="' + esc(c.key) + '" data-k="' + kind + '" data-i="' + esc(i) + '" title="' + esc(i + ': ' + c.name) + '" aria-label="' + esc(i + ', ' + c.name) + '"></button>'
              : '<span class="cell off" aria-hidden="true"></span>') + '</td>';
          }).join('') + '</tr>');
    }
  };
  // Families are applied to HAZARDS ONLY, deliberately.
  //
  // Hazards are mechanisms — a handful of them, reworded per industry, so
  // grouping reveals the shared structure. Exposures are assets — EHR systems,
  // SCADA, student information systems — and their specificity IS the content.
  // Grouping them produced an "Other" bucket of 38 unrelated entries, which
  // told us nothing. So exposures always show as reported.
  const H = MODE === 'fam' ? byFamily(D.hazards) : D.hazards;
  const E = D.exposures;
  CUR = { h: H, e: E };
  const head = '<thead><tr><th>' + (MODE === 'fam' ? 'Hazard family / exposure' : 'Category as reported') + '</th><th class="reach">Reach</th>'
    + INDS.map((i) => '<th class="rot"><div>' + esc(short(i)) + '</div></th>').join('') + '</tr></thead>';
  $('#matrix').innerHTML = head + '<tbody>' + (section(H, 'h'), section(E, 'e'), rows.join('')) + '</tbody>';

  const uniq = E.filter((c) => Object.keys(c.inds).length === 1).length;
  $('#mnote').innerHTML = MODE === 'fam'
    ? '<b>Hazards</b> are grouped into families, because industries reported the same mechanism under different wordings. “Insider and Credential Risk” and '
      + '“Insider Identity and Privileged Access Risk” are one family. Grouped, five hazard families reach <b>every industry</b>. '
      + '<b>Exposures are left as reported</b> on purpose: they are assets, not mechanisms, and their specificity is the content, and grouping them just produced a meaningless “Other” bucket. '
      + '<b>' + uniq + ' of ' + E.length + '</b> exposures appear in only one industry. '
      + 'That asymmetry is the finding. <em>How</em> you get attacked is nearly universal, <em>what you stand to lose</em> is almost entirely industry-specific.'
    : 'Hazard labels exactly as each industry’s research reported them. The long tail of 1/14 rows is mostly wording variation rather than genuinely unique risk. '
      + 'which is why “By family” compares industries better. Click any cell for that industry’s specifics.';
}
let CUR = { h: [], e: [] };
$('#bFam').onclick = () => { MODE = 'fam'; $('#bFam').setAttribute('aria-pressed', 'true'); $('#bRaw').setAttribute('aria-pressed', 'false'); buildMatrix(); };
$('#bRaw').onclick = () => { MODE = 'raw'; $('#bRaw').setAttribute('aria-pressed', 'true'); $('#bFam').setAttribute('aria-pressed', 'false'); buildMatrix(); };
$('#matrix').addEventListener('click', (e) => {
  const b = e.target.closest('.cell[data-c]'); if (!b) return;
  const list = b.dataset.k === 'h' ? CUR.h : CUR.e;
  showCat(list.find((c) => c.key === b.dataset.c), b.dataset.i, b.dataset.k);
});

/* ---------- category detail ---------- */
function showCat(c, focusInd, kindHint) {
  if (!c) return;
  const kind = (kindHint ? kindHint === 'h' : D.hazards.includes(c)) ? 'Hazard' : 'Exposure';
  const names = Object.keys(c.inds);
  const ordered = focusInd ? [focusInd, ...names.filter((n) => n !== focusInd)] : names;
  const isFam = !!c.members;
  open('<div class="kicker">' + kind + (isFam ? ' family' : '') + ' · present in ' + names.length + ' of ' + INDS.length + ' industries</div>'
    + '<h2>' + esc(c.name) + '</h2>'
    + (c.desc ? '<p>' + esc(c.desc) + '</p>' : '')
    + (isFam && c.members.length > 1
        ? '<h4>Reported under ' + c.members.length + ' labels</h4><p>'
          + c.members.map((m) => '<span class="tag">' + esc(m.name) + '</span>').join('') + '</p>'
        : '')
    + ordered.map((n) => {
        const v = c.inds[n];
        const raws = Array.isArray(v.raw) ? [...new Set(v.raw)] : [v.raw];
        return '<h4>' + esc(n) + (n === focusInd ? ' (selected)' : '') + '</h4>'
          + (isFam ? '<p style="font-size:12px;margin-bottom:5px">' + raws.map((r) => esc(r)).join(' · ') + '</p>' : '')
          + '<ul>' + v.subs.map((s) => '<li>' + esc(s) + '</li>').join('') + '</ul>';
      }).join(''));
}

/* ---------- industries ---------- */
function renderInds(f) {
  f = (f || '').toLowerCase();
  $('#inds').innerHTML = D.industries
    .filter((i) => !f || (i.name + i.overview + i.distinct).toLowerCase().includes(f))
    .map((i, idx) => {
      const hz = D.hazards.filter((c) => c.inds[i.name]).length;
      const ex = D.exposures.filter((c) => c.inds[i.name]).length;
      return '<div class="card clickable" data-ind="' + esc(i.name) + '" tabindex="0" role="button">'
        + '<h3>' + esc(i.name) + '</h3>'
        + '<div class="meta">' + (i.bulk ? num(i.bulk.total) + ' victims scraped · ' : '') + i.incidents.length + ' researched</div>'
        + '<p>' + esc((i.distinct || i.overview).slice(0, 190)) + '…</p>'
        + '<span class="tag h">' + hz + ' hazards</span><span class="tag e">' + ex + ' exposures</span>'
        + '</div>';
    }).join('') || '<p class="note">No industries match.</p>';
}
function showInd(name) {
  const i = D.industries.find((x) => x.name === name); if (!i) return;
  const hz = D.hazards.filter((c) => c.inds[name]), ex = D.exposures.filter((c) => c.inds[name]);
  let bulkHtml = '';
  if (i.bulk) {
    const ys = Object.keys(i.bulk.years).sort();
    const max = Math.max(...ys.map((y) => i.bulk.years[y]));
    bulkHtml = '<h4>Leak-site scrape: ' + num(i.bulk.total) + ' victims</h4>'
      + '<div class="years">' + ys.map((y) => '<div style="height:' + Math.round((i.bulk.years[y] / max) * 100) + '%" title="' + y + ': ' + i.bulk.years[y] + '"></div>').join('') + '</div>'
      + '<div class="ylab">' + ys.map((y) => '<span>' + y.slice(2) + '</span>').join('') + '</div>'
      + '<p style="margin-top:8px">Top groups: ' + i.bulk.groups.map((g) => esc(g[0]) + ' (' + g[1] + ')').join(', ') + '.<br>'
      + 'Only <b>' + i.bulk.pressPct + '%</b> of records carry a press link and <b>' + i.bulk.ransomPct + '%</b> an explicit ransom figure. That is why the researched layer below is hand-built.</p>';
  }
  open('<div class="kicker">Industry' + (i.tag ? ' · scraped as “' + esc(i.tag) + '”' : '') + '</div>'
    + '<h2>' + esc(i.name) + '</h2>'
    + (i.distinct ? '<p>' + esc(i.distinct) + '</p>' : '')
    + (i.leverage ? '<h4>Primary extortion leverage</h4><p>' + esc(i.leverage) + '</p>' : '')
    + (i.tolerance ? '<h4>Downtime tolerance</h4><p>' + esc(i.tolerance) + '</p>' : '')
    + bulkHtml
    + '<h4>Hazards (' + hz.length + ')</h4><p>' + hz.map((c) => '<span class="tag h">' + esc(c.name) + '</span>').join('') + '</p>'
    + '<h4>Exposures (' + ex.length + ')</h4><p>' + ex.map((c) => '<span class="tag e">' + esc(c.name) + '</span>').join('') + '</p>'
    + '<h4>Researched incidents (' + i.incidents.length + ')</h4>' + i.incidents.map(inc).join('')
    + (i.stats.length ? '<h4>Industry statistics (' + i.stats.length + ')</h4>'
        + i.stats.map((s) => '<div class="statrow"><span class="m"><b>' + esc(s.m) + '</b><br>' + esc(s.v) + '</span><span class="s">' + (s.u ? '<a href="' + esc(s.u) + '" target="_blank" rel="noopener">' + esc(s.s) + '</a>' : esc(s.s)) + '</span></div>').join('') : '')
    + '<p class="note">' + esc(i.overview) + '</p>');
}
function inc(e) {
  return '<div class="inc"><b>' + esc(e.v) + '</b>'
    + '<div class="f"><i>Group</i>' + (e.g ? esc(e.g) : 'n/a') + (e.d ? ' · ' + esc(e.d) : '') + (e.c ? ' · ' + esc(e.c) : '') + '</div>'
    + '<div class="f"><i>Financial</i>' + fmt(e.fin) + '</div>'
    + '<div class="f"><i>Ransom</i>' + fmt(e.ran) + '</div>'
    + '<div class="f"><i>Downtime</i>' + fmt(e.dt) + '</div>'
    + (e.di ? '<div class="f"><i>Data</i>' + fmt(e.di) + '</div>' : '')
    + (e.src.length ? '<div class="f srcs"><i>Sources</i>' + e.src.map((u, n) => '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + (n + 1) + '</a>').join('') + '</div>' : '')
    + '</div>';
}

/* ---------- categories ---------- */
function renderCats(f) {
  f = (f || '').toLowerCase();
  const all = [...D.hazards.map((c) => [c, 'h']), ...D.exposures.map((c) => [c, 'e'])];
  $('#cats').innerHTML = all.filter(([c]) => {
      if (!f) return true;
      if ((c.name + c.desc).toLowerCase().includes(f)) return true;
      return Object.values(c.inds).some((v) => v.subs.some((s) => s.toLowerCase().includes(f)));
    }).map(([c, k]) => {
      const n = Object.keys(c.inds).length;
      const subs = Object.values(c.inds).reduce((m, v) => m + v.subs.length, 0);
      return '<div class="card clickable" data-cat="' + esc(c.key) + '" data-kind="' + k + '" tabindex="0" role="button">'
        + '<h3>' + esc(c.name) + '</h3>'
        + '<div class="meta">' + (k === 'h' ? 'Hazard' : 'Exposure') + ' · ' + n + '/' + INDS.length + ' industries · ' + subs + ' subcategories</div>'
        + '<p>' + esc((c.desc || '').slice(0, 165)) + (c.desc.length > 165 ? '…' : '') + '</p>'
        + Object.keys(c.inds).slice(0, 4).map((i) => '<span class="tag">' + esc(short(i)) + '</span>').join('')
        + (n > 4 ? '<span class="tag">+' + (n - 4) + '</span>' : '')
        + '</div>';
    }).join('') || '<p class="note">Nothing matches.</p>';
}

/* ---------- incidents ---------- */
const ALLINC = D.industries.flatMap((i) => i.incidents.map((e) => ({ ...e, ind: i.name })));
function renderIncs(f) {
  f = (f || '').toLowerCase();
  $('#incs').innerHTML = ALLINC
    .filter((e) => !f || (e.v + e.g + e.fin + e.dt + e.s + e.ind).toLowerCase().includes(f))
    .map((e, n) => '<div class="card clickable" data-inc="' + n + '" tabindex="0" role="button">'
      + '<h3>' + esc(e.v) + '</h3>'
      + '<div class="meta">' + esc(e.ind) + (e.d ? ' · ' + esc(e.d) : '') + '</div>'
      + '<p>' + esc((e.s || '').slice(0, 150)) + '…</p>'
      + (e.g ? '<span class="tag">' + esc(e.g.slice(0, 34)) + '</span>' : '')
      + (e.fin && !ND.test(e.fin) ? '<span class="tag h">loss reported</span>' : '')
      + '</div>').join('') || '<p class="note">No incidents match.</p>';
}

/* ---------- synthesis ---------- */
$('#syn').innerHTML = '<h2 style="font-size:19px;margin-bottom:10px">How ransomware differs across industries</h2>'
  + D.comparison.split(/\\n\\n+/).map((p) => '<p>' + esc(p) + '</p>').join('')
  + (D.highest.length ? '<h3>Highest-risk industries</h3>' + D.highest.map((t) => '<p>' + esc(t) + '</p>').join('') : '')
  + (D.takeaways.length ? '<h3>Key takeaways</h3><ul style="color:var(--muted);font-size:14px;line-height:1.7">'
      + D.takeaways.map((t) => '<li style="margin-bottom:7px">' + esc(t) + '</li>').join('') + '</ul>' : '')
  + (D.global.length ? '<h3>Global statistics</h3>' + D.global.map((s) =>
      '<div class="statrow"><span class="m"><b>' + esc(s.m) + '</b><br>' + esc(s.v) + '</span>'
      + '<span class="s">' + (s.u ? '<a href="' + esc(s.u) + '" target="_blank" rel="noopener">' + esc(s.s) + '</a>' : esc(s.s)) + '</span></div>').join('') : '');

/* ---------- wiring ---------- */
function delegate(sel, attr, fn) {
  const el = $(sel);
  el.addEventListener('click', (e) => { const c = e.target.closest('[' + attr + ']'); if (c) fn(c); });
  el.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const c = e.target.closest('[' + attr + ']'); if (c) { e.preventDefault(); fn(c); }
  });
}
delegate('#inds', 'data-ind', (c) => showInd(c.dataset.ind));
delegate('#cats', 'data-cat', (c) => showCat((c.dataset.kind === 'h' ? D.hazards : D.exposures).find((x) => x.key === c.dataset.cat)));
delegate('#incs', 'data-inc', (c) => {
  const e = ALLINC[+c.dataset.inc];
  open('<div class="kicker">' + esc(e.ind) + '</div><h2>' + esc(e.v) + '</h2><p>' + esc(e.s) + '</p>' + inc(e));
});
$('#qi').addEventListener('input', (e) => renderInds(e.target.value));
$('#qc').addEventListener('input', (e) => renderCats(e.target.value));
$('#qn').addEventListener('input', (e) => renderIncs(e.target.value));

buildMatrix(); renderInds(); renderCats(); renderIncs();
</script>
</body>
</html>`;

const out = path.join(path.resolve(__dirname, '..'), 'explorer.html');
fs.writeFileSync(out, html.replace('__DATA__', JSON.stringify(clean(payload))).replace('__IND__', String(industries.length)));
const kb = Math.round(fs.statSync(out).size / 1024);
console.log(`explorer written -> ${out} (${kb} KB)`);
console.log(`  ${payload.meta.industries} industries · ${payload.meta.incidents} incidents · ${payload.meta.hazards} hazards · ${payload.meta.exposures} exposures`);
console.log(`  bulk scrape summarised: ${num2(payload.meta.bulkTotal)} victims across ${Object.keys(bulk).length} sectors`);
function num2(n) { return n.toLocaleString('en-US'); }
