// ===========================================================================
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
