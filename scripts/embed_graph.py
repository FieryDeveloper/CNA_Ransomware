"""
embed_graph.py — add a vector index to the Neo4j graph for GraphRAG.

Runs ONCE (re-run after reloading the graph). It reads the text-bearing nodes,
computes an embedding for each with a LOCAL model (no API, no cost), writes the
vector back onto the node, and creates a Neo4j vector index over them. After
this, ask.py can retrieve by meaning and then traverse the graph for context.

Why local embeddings: the corpus is ~1,300 short texts. all-MiniLM-L6-v2 (384
dims) embeds the whole thing in seconds on a CPU and keeps your OpenAI key out of
the indexing path entirely. The key is only ever used later, optionally, to phrase
a final answer (see ask.py --answer).

Requires Neo4j 5.11+ (vector index support) with the graph already loaded
(data/graph/load.cypher).

Setup:
  pip install neo4j sentence-transformers
  export NEO4J_URI='bolt://localhost:7687'
  export NEO4J_USER='neo4j'
  export NEO4J_PASSWORD='<your password>'
  python scripts/embed_graph.py
"""

from __future__ import annotations

import os
import sys

MODEL_NAME = "all-MiniLM-L6-v2"
DIM = 384
INDEX = "rag_vec"

# Which nodes carry meaning worth retrieving, and how to assemble their text.
# coalesce keeps a null property from poisoning the concatenation.
NODE_TEXT = {
    "Industry": "coalesce(n.id,'') + '. ' + coalesce(n.overview,'') + ' ' + coalesce(n.distinct,'') + ' ' + coalesce(n.extortion_leverage,'')",
    "Hazard": "coalesce(n.name,'') + '. ' + coalesce(n.description,'')",
    "Exposure": "coalesce(n.name,'') + '. ' + coalesce(n.description,'')",
    "Incident": "coalesce(n.victim,'') + '. ' + coalesce(n.summary,'') + ' Impact: ' + coalesce(n.financial_impact,'') + ' Downtime: ' + coalesce(n.downtime,'')",
    "Subcategory": "coalesce(n.name,'') + ' (' + coalesce(n.parent,'') + ')'",
}


def main() -> int:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pw = os.environ.get("NEO4J_PASSWORD")
    if not pw:
        raise SystemExit("set NEO4J_PASSWORD (and NEO4J_URI / NEO4J_USER if not default)")

    try:
        from neo4j import GraphDatabase
    except ImportError:
        raise SystemExit("pip install neo4j")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise SystemExit("pip install sentence-transformers")

    print(f"loading model {MODEL_NAME} (first run downloads ~90MB)...")
    model = SentenceTransformer(MODEL_NAME)

    driver = GraphDatabase.driver(uri, auth=(user, pw))
    driver.verify_connectivity()
    print(f"connected -> {uri}\n")

    total = 0
    with driver.session() as session:
        for label, text_expr in NODE_TEXT.items():
            rows = session.run(
                f"MATCH (n:{label}) WHERE {text_expr.replace('n.', 'n.')} IS NOT NULL "
                f"RETURN elementId(n) AS id, {text_expr} AS text"
            ).data()
            rows = [r for r in rows if (r["text"] or "").strip()]
            if not rows:
                print(f"  {label:12} no text nodes")
                continue

            vecs = model.encode([r["text"] for r in rows], normalize_embeddings=True,
                                show_progress_bar=False)
            payload = [{"id": r["id"], "vec": v.tolist(), "text": r["text"][:2000]}
                       for r, v in zip(rows, vecs)]

            # Tag every embedded node with a shared :Doc label so one vector
            # index can serve retrieval across all of them.
            session.run(
                "UNWIND $rows AS row MATCH (n) WHERE elementId(n) = row.id "
                "SET n:Doc, n.embedding = row.vec, n.rag_text = row.text",
                rows=payload,
            )
            print(f"  {label:12} {len(rows):>4} embedded")
            total += len(rows)

        # Combined index (search everything) ...
        session.run(
            f"CREATE VECTOR INDEX {INDEX} IF NOT EXISTS FOR (n:Doc) ON (n.embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}",
            dim=DIM,
        )
        # ... plus one index PER node type, so retrieval can pull guaranteed
        # context from each (an incident AND an industry AND taxonomy), instead
        # of whichever type happens to dominate the top-k of a single index.
        for label in NODE_TEXT:
            session.run(
                f"CREATE VECTOR INDEX vec_{label.lower()} IF NOT EXISTS FOR (n:{label}) ON (n.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}",
                dim=DIM,
            )
        print(f"\nindexes ready: '{INDEX}' (all {total} nodes) + per-type "
              + ", ".join(f"vec_{l.lower()}" for l in NODE_TEXT))

    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
