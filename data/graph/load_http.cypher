// HTTP variant — serve this dir: python -m http.server 877, then run in Browser or via driver.

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

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_industry.csv' AS r
MERGE (n:Industry {id: r.id})
SET n.sector_tag = r.sector_tag, n.incident_count = toInteger(r.incident_count),
    n.overview = r.overview, n.distinct = r.distinct,
    n.extortion_leverage = r.extortion_leverage, n.downtime_tolerance = r.downtime_tolerance;

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_hazard.csv' AS r
MERGE (n:Hazard {id: r.id}) SET n.name = r.name, n.description = r.description;

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_exposure.csv' AS r
MERGE (n:Exposure {id: r.id}) SET n.name = r.name, n.description = r.description;

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_subcategory.csv' AS r
MERGE (n:Subcategory {id: r.id}) SET n.name = r.name, n.parent = r.parent, n.kind = r.kind;

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_incident.csv' AS r
MERGE (n:Incident {id: r.id})
SET n.victim = r.victim, n.date = r.date, n.country = r.country,
    n.financial_impact = r.financial_impact, n.ransom = r.ransom,
    n.downtime = r.downtime, n.data_impact = r.data_impact,
    n.summary = r.summary, n.source_count = toInteger(r.source_count);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_company.csv' AS r MERGE (:Company {id: r.id});
LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_group.csv' AS r MERGE (:Group {id: r.id});
LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_country.csv' AS r MERGE (:Country {id: r.id});
LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_source.csv' AS r MERGE (n:Source {id: r.id}) SET n.host = r.host;
LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_theme.csv' AS r MERGE (n:Theme {id: r.id}) SET n.name = r.name, n.kind = r.kind;

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_statistic.csv' AS r
MERGE (n:Statistic {id: r.id})
SET n.metric = r.metric, n.value = r.value, n.source = r.source,
    n.source_url = r.source_url, n.scope = r.scope;

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_faces.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Hazard {id: r.to}) MERGE (a)-[:FACES]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_exposes.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Exposure {id: r.to}) MERGE (a)-[:EXPOSES]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_includes.csv' AS r
MATCH (a {id: r.from}), (b:Subcategory {id: r.to}) MERGE (a)-[:INCLUDES]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_had_incident.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Incident {id: r.to}) MERGE (a)-[:HAD_INCIDENT]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_hit.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Company {id: r.to}) MERGE (a)-[:HIT]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_perpetrated_by.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Group {id: r.to}) MERGE (a)-[:PERPETRATED_BY]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_occurred_in.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Country {id: r.to}) MERGE (a)-[:OCCURRED_IN]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_cited_by.csv' AS r
MATCH (a:Incident {id: r.from}), (b:Source {id: r.to}) MERGE (a)-[:CITED_BY]->(b);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/rels_measured_by.csv' AS r
MATCH (a:Industry {id: r.from}), (b:Statistic {id: r.to}) MERGE (a)-[:MEASURED_BY]->(b);

// Bulk leak-site victims: the full ~27k scrape, not just the researched
// exemplars. Skip this block if you only want the curated layer.
// Batched so it does not build one huge transaction. Neo4j 5 syntax; on 4.x
// replace the CALL {} IN TRANSACTIONS wrapper with ':auto USING PERIODIC COMMIT 1000'.
CREATE INDEX victim_name IF NOT EXISTS FOR (n:Victim) ON (n.name);

LOAD CSV WITH HEADERS FROM 'http://localhost:877/nodes_victim_bulk.csv' AS r
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
