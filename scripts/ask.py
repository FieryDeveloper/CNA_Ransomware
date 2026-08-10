"""
ask.py — natural-language questions over the ransomware knowledge graph.

A small router with three lanes, because "ask the data anything" is really three
different problems:

  SEMANTIC   "why is healthcare's risk unique?", "what's exposed in a hospital?"
             -> embed the question, vector-search the graph, pull 1-hop context.
             This is the GraphRAG lane. Runs with local embeddings, no API.

  RELATIONAL "which groups hit both healthcare and finance?", "what's exposed in
             healthcare but not manufacturing?"
             -> a graph TRAVERSAL. Vectors can't do this; Cypher can.

  ANALYTICAL "how many victims in 2025?", "top 5 groups in manufacturing"
             -> an aggregation over the bulk layer. Cypher COUNT/ORDER, not RAG.

Routing is keyword-heuristic (cheap, no API). The semantic lane always works as a
fallback. By default the tool RETRIEVES and shows you the evidence; pass --answer
to additionally have an LLM phrase a prose answer from that evidence (the only
step that touches an API, and only if you opt in).

Setup:
  pip install neo4j sentence-transformers
  export NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
  python scripts/embed_graph.py          # once, builds the vector index
  python scripts/ask.py "why is healthcare targeted so heavily?"
  python scripts/ask.py "top 5 groups in manufacturing"
  python scripts/ask.py "what's exposed in healthcare but not manufacturing?"
  python scripts/ask.py "why is healthcare unique?" --answer   # + LLM synthesis

--answer uses OpenAI if OPENAI_API_KEY is set (model from OPENAI_MODEL, default
gpt-4o-mini), else Anthropic if ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import os
import re
import sys

INDEX = "rag_vec"
MODEL_NAME = "all-MiniLM-L6-v2"

# --- lane routing -----------------------------------------------------------
ANALYTICAL = re.compile(r"\b(how many|count|number of|total|most active|top \d|top |busiest|by year|per year|how much|average|biggest|largest|costliest)\b", re.I)
RELATIONAL = re.compile(r"\b(both|also hit|shared|in common|but not|as well as|across (industries|sectors)|footprint|which groups?.*(and|both))\b", re.I)

# keyword -> Industry node id (DBIR name), used by the relational lane.
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

# keyword -> ransomware.live sector tag on Victim nodes (differs from the DBIR
# name: victims are tagged "Education", not "Educational Services"). Used by the
# analytical lane, which queries the bulk :Victim layer.
SECTOR_TAG = {
    "healthcare": "Healthcare", "finance": "Financial Services", "financial": "Financial Services",
    "manufacturing": "Manufacturing", "education": "Education", "energy": "Energy",
    "retail": "Consumer Services", "government": "Public Sector", "public": "Public Sector",
    "technology": "Technology", "transportation": "Transportation/Logistics", "construction": "Construction",
    "telecom": "Telecommunication", "agriculture": "Agriculture and Food Production",
    "hospitality": "Hospitality and Tourism", "business": "Business Services",
}


def find_sector_tag(q: str):
    for k, v in SECTOR_TAG.items():
        if k in q.lower():
            return v
    return None


def find_industries(q: str) -> list[str]:
    found = []
    for k, v in INDUSTRY_HINTS.items():
        if k in q.lower() and v not in found:
            found.append(v)
    return found


def connect():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        raise SystemExit("pip install neo4j")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pw = os.environ.get("NEO4J_PASSWORD")
    if not pw:
        raise SystemExit("set NEO4J_PASSWORD (and NEO4J_URI / NEO4J_USER if not default)")
    d = GraphDatabase.driver(uri, auth=(user, pw))
    d.verify_connectivity()
    return d


# --- lanes ------------------------------------------------------------------
def lane_analytical(session, q: str):
    if "by year" in q.lower() or "per year" in q.lower():
        rows = session.run(
            "MATCH (v:Victim) WHERE v.attackdate <> '' "
            "RETURN left(v.attackdate,4) AS year, count(*) AS n ORDER BY year").data()
        return "victims per year", [(r["year"], r["n"]) for r in rows]
    tag = find_sector_tag(q)
    if tag:
        rows = session.run(
            "MATCH (v:Victim)-[:ATTACKED_BY]->(g:Group) WHERE toLower(v.sector) = toLower($s) "
            "RETURN g.id AS group, count(*) AS n ORDER BY n DESC LIMIT 10", s=tag).data()
        if rows:
            return f"top groups in {tag}", [(r["group"], r["n"]) for r in rows]
    rows = session.run(
        "MATCH (v:Victim)-[:ATTACKED_BY]->(g:Group) "
        "RETURN g.id AS group, count(*) AS n ORDER BY n DESC LIMIT 10").data()
    return "most active groups overall", [(r["group"], r["n"]) for r in rows]


def lane_relational(session, q: str):
    inds = find_industries(q)
    if "but not" in q.lower() and len(inds) >= 2:
        a, b = inds[0], inds[1]
        rows = session.run(
            "MATCH (:Industry {id:$a})-[:EXPOSES]->(e:Exposure) "
            "WHERE NOT EXISTS { MATCH (:Industry {id:$b})-[:EXPOSES]->(e) } "
            "RETURN e.name AS name", a=a, b=b).data()
        return f"exposed in {a} but not {b}", [r["name"] for r in rows]
    if len(inds) >= 2:
        a, b = inds[0], inds[1]
        rows = session.run(
            "MATCH (:Industry {id:$a})-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g:Group) "
            "WITH collect(DISTINCT g.id) AS ga "
            "MATCH (:Industry {id:$b})-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g2:Group) "
            "WHERE g2.id IN ga RETURN DISTINCT g2.id AS group", a=a, b=b).data()
        return f"groups hitting both {a} and {b}", [r["group"] for r in rows]
    # single-industry footprint of the groups that hit it
    if inds:
        rows = session.run(
            "MATCH (:Industry {id:$a})-[:HAD_INCIDENT]->(:Incident)-[:PERPETRATED_BY]->(g:Group) "
            "RETURN DISTINCT g.id AS group", a=inds[0]).data()
        return f"groups seen in {inds[0]} (researched incidents)", [r["group"] for r in rows]
    return None, None


def lane_semantic(session, q: str, model, k: int):
    qv = model.encode([q], normalize_embeddings=True)[0].tolist()
    rows = session.run(
        f"CALL db.index.vector.queryNodes('{INDEX}', $k, $qv) YIELD node, score "
        "OPTIONAL MATCH (node)-[r]-(nb) "
        "WITH node, score, collect(DISTINCT coalesce(nb.name, nb.victim, nb.id))[0..6] AS context "
        "RETURN labels(node) AS labels, node.rag_text AS text, score, context "
        "ORDER BY score DESC", k=k, qv=qv).data()
    return rows


# --- optional LLM synthesis (the only API-touching step) --------------------
def synthesize(question: str, contexts: list[str]) -> str | None:
    joined = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(contexts))
    prompt = (f"Answer the question using ONLY the context from a ransomware risk "
              f"knowledge graph. Cite the [n] snippets you use. If the context does "
              f"not contain the answer, say so.\n\nQuestion: {question}\n\nContext:\n{joined}")
    if os.environ.get("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
        except ImportError:
            return "(pip install openai to enable --answer)"
        client = OpenAI()
        r = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}], temperature=0)
        return r.choices[0].message.content
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
        except ImportError:
            return "(pip install anthropic to enable --answer)"
        c = anthropic.Anthropic()
        r = c.messages.create(model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                              max_tokens=600, messages=[{"role": "user", "content": prompt}])
        return r.content[0].text
    return "(set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable --answer)"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    answer = "--answer" in sys.argv
    k = 6
    for a in sys.argv:
        if a.startswith("--k="):
            k = int(a.split("=")[1])
    if not args:
        raise SystemExit('usage: python scripts/ask.py "your question" [--answer] [--k=6]')
    q = " ".join(args)

    driver = connect()
    with driver.session() as session:
        if ANALYTICAL.search(q):
            title, rows = lane_analytical(session, q)
            print(f"[analytical] {title}\n")
            for name, n in rows:
                print(f"  {n:>7,}  {name}")
        elif RELATIONAL.search(q):
            title, items = lane_relational(session, q)
            if title is None:
                print("could not resolve two industries; try naming them explicitly.")
            else:
                print(f"[relational] {title}\n")
                for it in items:
                    print(f"  - {it}")
        else:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise SystemExit("pip install sentence-transformers")
            model = SentenceTransformer(MODEL_NAME)
            rows = lane_semantic(session, q, model, k)
            print(f"[semantic] top {len(rows)} matches\n")
            for r in rows:
                lab = "/".join([x for x in r["labels"] if x != "Doc"]) or "Doc"
                print(f"  ({lab}, score {r['score']:.3f}) {(''.join(r['text'])[:200])}")
                if r["context"]:
                    print(f"      linked: {', '.join(str(c) for c in r['context'] if c)}")
                print()
            if answer:
                print("-" * 60)
                print(synthesize(q, [" ".join(r["text"].split()) for r in rows]))

    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
