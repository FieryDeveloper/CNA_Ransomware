#!/usr/bin/env node
/**
 * server.js — tiny read-only API in front of Atlas, and it serves the explorer.
 *
 * A static HTML file cannot talk to MongoDB directly, so this sits between them.
 * It serves explorer.html at / and exposes read-only JSON the Insights tab
 * fetches. When the page is served from here it shows LIVE Atlas data; opened
 * as a plain file it falls back to the snapshot baked into the HTML. So the
 * self-contained file keeps working either way — this only adds live mode.
 *
 * No framework: Node's built-in http + the official mongodb driver.
 *
 * Setup:
 *   npm install                      # installs the mongodb driver
 *   export MONGODB_URI='mongodb+srv://...'   # same as load_mongo.py
 *   node scripts/server.js           # -> http://localhost:8080
 *
 * Endpoints (all read-only):
 *   GET /                 the explorer
 *   GET /api/health       { ok, db }
 *   GET /api/insights     dashboard aggregates, mapped to the page's shape
 *   GET /api/industries   the 14 industry docs
 *   GET /api/synthesis    cross-industry narrative + global stats
 */

const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 8080;
const DB_NAME = process.env.MONGODB_DB || 'cna_ransomware';
const HTML = path.resolve(__dirname, '..', 'explorer.html');

let MongoClient;
try { ({ MongoClient } = require('mongodb')); }
catch { console.error('mongodb driver missing — run: npm install'); process.exit(1); }

const uri = process.env.MONGODB_URI;
if (!uri) { console.error('set MONGODB_URI (see load_mongo.py setup notes)'); process.exit(1); }

const client = new MongoClient(uri);
let db = null;

// Map the stored insights doc into exactly the shape the Insights tab expects,
// so the front-end code is identical whether data is inlined or fetched.
function mapInsights(d) {
  if (!d) return null;
  const money = (a) => (a || []).map((x) => ({ victim: x.victim, industry: x.industry, usd: x.usd, raw: x.text }));
  return {
    total: d.total_victims,
    groupCount: d.group_count,
    countryCount: d.country_count,
    bySector: d.by_sector,
    byYear: d.by_year,
    topGroups: d.top_groups,
    topCountries: d.top_countries,
    heatmap: d.heatmap,
    financial: money(d.costliest),
    ransom: money(d.largest_ransoms),
    generated_at: d.generated_at,
  };
}

const send = (res, code, body, type = 'application/json') => {
  res.writeHead(code, { 'Content-Type': type, 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
};

const server = http.createServer(async (req, res) => {
  const url = req.url.split('?')[0];
  try {
    if (url === '/' || url === '/explorer.html') {
      return send(res, 200, fs.readFileSync(HTML, 'utf8'), 'text/html; charset=utf-8');
    }
    if (url === '/api/health') {
      await db.command({ ping: 1 });
      return send(res, 200, { ok: true, db: DB_NAME });
    }
    if (url === '/api/insights') {
      const doc = await db.collection('insights').findOne({ _id: 'current' });
      return send(res, 200, mapInsights(doc) || {});
    }
    if (url === '/api/industries') {
      return send(res, 200, await db.collection('industries').find().toArray());
    }
    if (url === '/api/synthesis') {
      return send(res, 200, await db.collection('synthesis').findOne({ _id: 'current' }) || {});
    }
    return send(res, 404, { error: 'not found' });
  } catch (e) {
    return send(res, 500, { error: String(e && e.message || e) });
  }
});

client.connect()
  .then(() => { db = client.db(DB_NAME); return db.command({ ping: 1 }); })
  .then(() => server.listen(PORT, () => {
    console.log(`serving explorer + live API on http://localhost:${PORT}`);
    console.log(`  DB: ${DB_NAME}  |  open the URL for live Atlas data`);
  }))
  .catch((e) => { console.error('cannot reach Atlas:', e.message); process.exit(1); });
