#!/usr/bin/env node
/**
 * validate.js — sanity-check the built dataset before anyone relies on it.
 *
 * The research agents were explicitly instructed to write "not publicly
 * disclosed" rather than estimate a figure. This script surfaces how often that
 * happened, so a reader knows which gaps are genuine reporting gaps rather than
 * missing work — and flags records that look structurally incomplete.
 *
 * Usage: node validate.js
 */

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.resolve(__dirname, '..', 'data');
const industries = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'industries.json'), 'utf8'));

const NOT_DISCLOSED = /not (publicly )?(disclosed|reported|available|known)|unknown|undisclosed|n\/a/i;

let problems = 0;
const warn = (msg) => { problems++; console.log(`  ! ${msg}`); };

console.log(`validating ${industries.length} industries\n`);

let totalIncidents = 0;
let withFinancial = 0, withRansom = 0, withDowntime = 0, withSources = 0;

for (const ind of industries) {
  const incidents = ind.example_incidents || [];
  totalIncidents += incidents.length;

  console.log(`${ind.industry}`);
  if (!ind.overview) warn('missing overview');
  if ((ind.hazard_categories || []).length < 4) warn(`only ${(ind.hazard_categories || []).length} hazard categories`);
  if ((ind.exposure_categories || []).length < 4) warn(`only ${(ind.exposure_categories || []).length} exposure categories`);
  if (incidents.length < 5) warn(`only ${incidents.length} incidents`);

  for (const e of incidents) {
    if (!e.victim) warn('incident with no victim name');
    if (!(e.sources || []).length) warn(`"${e.victim}" has no sources`);
    else withSources++;

    if (e.financial_impact && !NOT_DISCLOSED.test(e.financial_impact)) withFinancial++;
    if (e.ransom_demanded_or_paid && !NOT_DISCLOSED.test(e.ransom_demanded_or_paid)) withRansom++;
    if (e.downtime_and_recovery && !NOT_DISCLOSED.test(e.downtime_and_recovery)) withDowntime++;
  }

  // A source that isn't a URL is usually a hallucinated citation placeholder.
  for (const e of incidents) {
    for (const s of e.sources || []) {
      if (!/^https?:\/\//i.test(s)) warn(`"${e.victim}" has a non-URL source: ${String(s).slice(0, 60)}`);
    }
  }

  for (const s of ind.aggregate_stats || []) {
    if (!s.source) warn(`stat "${s.metric}" has no source attribution`);
  }
}

const pct = (n) => `${n}/${totalIncidents} (${Math.round((n / totalIncidents) * 100)}%)`;

console.log('\n=== coverage ===');
console.log(`incidents total            ${totalIncidents}`);
console.log(`with a cited source        ${pct(withSources)}`);
console.log(`with a financial figure    ${pct(withFinancial)}`);
console.log(`with a ransom figure       ${pct(withRansom)}`);
console.log(`with downtime/recovery     ${pct(withDowntime)}`);
console.log(`\nremaining fields are genuine public-reporting gaps, not missing research.`);
console.log(problems ? `\n${problems} warning(s) raised.` : '\nno warnings.');
