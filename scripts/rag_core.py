"""
rag_core.py — the GraphRAG engine shared by the HTTP API (api.py) and CLI (ask.py).

One idea, three retrieval strategies, one answer path:

  EVERY question is answered by an LLM, but the CONTEXT it is grounded in depends
  on the question:

    analytical  ("how many", "top groups", "coverage", "costliest")
                -> context comes from MongoDB (the materialized `insights` doc
                   and targeted aggregations). Numbers come from the database,
                   never from the model's memory.

    relational  ("which groups hit both X and Y", "exposed in X but not Y")
                -> context comes from a Neo4j graph TRAVERSAL.

    semantic    ("why is healthcare targeted", "what is exposed in a hospital")
                -> context comes from Neo4j VECTOR search + a 1-hop expansion.
                   This is the GraphRAG lane.

The LLM only ever phrases an answer from retrieved evidence, so answers stay
grounded and cite their sources. Retrieval uses a LOCAL embedding model (no API);
the OpenAI/Anthropic call is only the final synthesis.

Env: NEO4J_URI/USER/PASSWORD, MONGODB_URI, and OPENAI_API_KEY or ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Load a repo-root .env if present, so api.py / ask.py run with one command
# instead of exported env vars each time. Optional — skipped if not installed.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

INDEX = "rag_vec"
EMB_MODEL = "all-MiniLM-L6-v2"
DB_NAME = os.environ.get("MONGODB_DB", "cna_ransomware")

ANALYTICAL = re.compile(r"\b(how many|how much|count|number of|total|most active|top \d|top |busiest|by year|per year|average|biggest|largest|costliest|coverage|disclos|how often|percentage|what share)\b", re.I)
RELATIONAL = re.compile(r"\b(both|also hit|shared|in common|but not|as well as|across (industries|sectors)|footprint)\b", re.I)

INDUSTRY_HINTS = {
    "healthcare": "Healthcare and Social Assistance", "finance": "Finance and Insurance",
    "financial": "Finance and Insurance", "manufacturing": "Manufacturing",
    "education": "Educational Services", "energy": "Energy and Utilities",
    "retail": "Retail Trade and Consumer Services", "government": "Public Administration (Government)",
    "public": "Public Administration (Government)", "technology": "Information Technology",
    "transportation": "Transportation and Warehousing", "construction": "Construction",
    "telecom": "Telecommunications", "agriculture": "Agriculture, Forestry, Fishing and Food Production",
    "hospitality": "Accommodation, Food Services, Arts and Entertainment",
}
SECTOR_TAG = {
    "healthcare": "Healthcare", "finance": "Financial Services", "financial": "Financial Services",
    "manufacturing": "Manufacturing", "education": "Education", "energy": "Energy",
    "retail": "Consumer Services", "government": "Public Sector", "public": "Public Sector",
    "technology": "Technology", "transportation": "Transportation/Logistics", "construction": "Construction",
    "telecom": "Telecommunication", "agriculture": "Agriculture and Food Production",
    "hospitality": "Hospitality and Tourism", "business": "Business Services",
}


def _hint(q, table):
    ql = q.lower()
    return [v for k, v in table.items() if k in ql]


class RagEngine:
    """Holds the connections/model so a long-running server initializes once."""

    def __init__(self):
        self.driver = None
        self.mongo = None
        self._model = None

    # --- lifecycle ---------------------------------------------------------
    def connect(self):
        """Wire whichever backends are configured. Each is independent: with
        only Mongo the analytical lane works; with only Neo4j the graph lanes
        work. Missing backends degrade to a clear error, never a crash."""
        pw = os.environ.get("NEO4J_PASSWORD")
        if pw:
            try:
                from neo4j import GraphDatabase
                self.driver = GraphDatabase.driver(
                    os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                    auth=(os.environ.get("NEO4J_USER", "neo4j"), pw))
                self.driver.verify_connectivity()
            except Exception as e:
                print(f"[rag] Neo4j unavailable: {e}")
                self.driver = None

        mongo_uri = os.environ.get("MONGODB_URI")
        if mongo_uri:
            try:
                from pymongo import MongoClient
                m = MongoClient(mongo_uri)
                m.admin.command("ping")
                self.mongo = m[DB_NAME]
            except Exception as e:
                print(f"[rag] MongoDB unavailable: {e}")
                self.mongo = None
        return self

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMB_MODEL)
        return self._model

    def close(self):
        if self.driver:
            self.driver.close()

    # --- routing -----------------------------------------------------------
    def classify(self, q: str) -> str:
        if RELATIONAL.search(q):
            return "relational"
        if ANALYTICAL.search(q):
            return "analytical"
        return "semantic"

    # --- retrieval ---------------------------------------------------------
    def _semantic_context(self, q: str, k: int = 6):
        qv = self.model.encode([q], normalize_embeddings=True)[0].tolist()
        with self.driver.session() as s:
            rows = s.run(
                f"CALL db.index.vector.queryNodes('{INDEX}', $k, $qv) YIELD node, score "
                "OPTIONAL MATCH (node)-[r]-(nb) "
                "WITH node, score, collect(DISTINCT coalesce(nb.name, nb.victim, nb.id))[0..6] AS ctx "
                "RETURN labels(node) AS labels, node.rag_text AS text, score, ctx "
                "ORDER BY score DESC", k=k, qv=qv).data()
        ev = [{"type": "/".join([l for l in r["labels"] if l != "Doc"]) or "Doc",
               "score": round(r["score"], 3), "text": r["text"], "linked": [c for c in r["ctx"] if c]}
              for r in rows]
        return ev, [r["text"] for r in rows]

    def _relational_context(self, q: str):
        inds = _hint(q, INDUSTRY_HINTS)
        with self.driver.session() as s:
            if "but not" in q.lower() and len(inds) >= 2:
                rows = s.run(
                    "MATCH (:Industry {id:$a})-[:EXPOSES]->(e:Exposure) "
                    "WHERE NOT EXISTS { MATCH (:Industry {id:$b})-[:EXPOSES]->(e) } RETURN e.name AS name",
                    a=inds[0], b=inds[1]).data()
                items = [r["name"] for r in rows]
                return [{"type": "Exposure", "text": n} for n in items], \
                    [f"Exposed in {inds[0]} but not {inds[1]}: " + "; ".join(items)]
            if len(inds) >= 2:
                rows = s.run(
                    "MATCH (:Industry {id:$a})-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g:Group) "
                    "WITH collect(DISTINCT g.id) AS ga "
                    "MATCH (:Industry {id:$b})-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g2:Group) "
                    "WHERE g2.id IN ga RETURN DISTINCT g2.id AS g", a=inds[0], b=inds[1]).data()
                items = [r["g"] for r in rows]
                return [{"type": "Group", "text": g} for g in items], \
                    [f"Groups hitting both {inds[0]} and {inds[1]}: " + "; ".join(items)]
        # fall back to semantic if we can't resolve a traversal
        return self._semantic_context(q)

    def _analytical_context(self, q: str):
        """Pull the relevant numbers from MongoDB (materialized insights + a
        targeted victim aggregation when a sector is named)."""
        if self.mongo is None:
            return self._semantic_context(q)
        ins = self.mongo["insights"].find_one({"_id": "current"}, {"_id": 0, "heatmap": 0}) or {}
        facts = {
            "total_victims": ins.get("total_victims"),
            "group_count": ins.get("group_count"),
            "country_count": ins.get("country_count"),
            "researched_incidents": ins.get("researched_incidents"),
            "by_sector": ins.get("by_sector"),
            "by_year": ins.get("by_year"),
            "top_groups": ins.get("top_groups"),
            "top_countries": ins.get("top_countries"),
            "coverage": ins.get("coverage"),
            "costliest": ins.get("costliest"),
            "largest_ransoms": ins.get("largest_ransoms"),
        }
        tags = _hint(q, SECTOR_TAG)
        if tags:
            rows = list(self.mongo["victims"].aggregate([
                {"$match": {"sector": tags[0]}},
                {"$group": {"_id": "$group", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}}, {"$limit": 10},
            ]))
            facts[f"top_groups_in_{tags[0]}"] = [{"group": r["_id"], "n": r["n"]} for r in rows if r["_id"]]
        import json
        return [{"type": "MongoDB insights", "text": "materialized aggregates + targeted query"}], \
            [json.dumps(facts, default=str)]

    # --- synthesis ---------------------------------------------------------
    def _synthesize(self, question: str, contexts, lane: str):
        joined = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(contexts))
        src = "a MongoDB analytics store" if lane == "analytical" else "a ransomware-risk knowledge graph"
        prompt = (f"You answer questions about ransomware risk using ONLY the context below, "
                  f"retrieved from {src}. Be concise and specific. Cite the [n] snippets you use. "
                  f"For counts and dollar figures, use the numbers in the context verbatim. If the "
                  f"context does not contain the answer, say so.\n\nQuestion: {question}\n\nContext:\n{joined}")
        if os.environ.get("OPENAI_API_KEY"):
            from openai import OpenAI
            r = OpenAI().chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}], temperature=0)
            return r.choices[0].message.content
        if os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic
            r = anthropic.Anthropic().messages.create(
                model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                max_tokens=700, messages=[{"role": "user", "content": prompt}])
            return r.content[0].text
        return None  # no key: caller still gets the evidence

    # --- public ------------------------------------------------------------
    def answer(self, question: str, synthesize: bool = True, k: int = 6) -> dict:
        lane = self.classify(question)
        if lane == "analytical":
            evidence, contexts = self._analytical_context(question)
        elif self.driver is None:
            # graph lanes need Neo4j; fall back to Mongo facts if available
            if self.mongo is not None:
                lane, (evidence, contexts) = "analytical", self._analytical_context(question)
            else:
                raise RuntimeError("this question needs the Neo4j graph, which is not connected")
        elif lane == "relational":
            evidence, contexts = self._relational_context(question)
        else:
            evidence, contexts = self._semantic_context(question, k)
        answer = self._synthesize(question, contexts, lane) if synthesize else None
        return {"question": question, "lane": lane, "answer": answer, "evidence": evidence,
                "synthesized": answer is not None}
