"""
api.py — the production HTTP API: GraphRAG question-answering + live insights.

A single FastAPI service that:
  POST /api/ask        ask a question in English; routed to Mongo (analytical) or
                       Neo4j GraphRAG (semantic/relational), then answered by an LLM
  GET  /api/insights   materialized dashboard aggregates from MongoDB (incl. coverage)
  GET  /api/industries the 14 industry docs
  GET  /api/synthesis  cross-industry narrative + global stats
  GET  /api/health     liveness + which backends are wired
  GET  /               serves explorer.html (so the site + API are one service)

This is the productionized replacement for the ask.py CLI: one long-running
process that holds the Neo4j driver, Mongo client and embedding model, and
answers over HTTP.

Run:
  pip install -r requirements.txt
  export NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
  export MONGODB_URI
  export OPENAI_API_KEY            # or ANTHROPIC_API_KEY
  python scripts/embed_graph.py    # once, builds the Neo4j vector index
  uvicorn scripts.api:app --host 0.0.0.0 --port 8080
     # or: python scripts/api.py

Example:
  curl -s localhost:8080/api/ask -H 'content-type: application/json' \
       -d '{"question":"why is healthcare targeted so heavily?"}' | jq
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Work whether launched as `python scripts/api.py` or `uvicorn scripts.api:app`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_core import RagEngine, DB_NAME

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "explorer.html"
CHAT = ROOT / "chat.html"

engine = RagEngine()


@asynccontextmanager
async def lifespan(app):
    try:
        engine.connect()  # wire Neo4j + Mongo once at boot
    except Exception as e:  # keep serving static + a clear health error
        print(f"[startup] backend not fully wired: {e}")
    yield


app = FastAPI(title="CNA Ransomware GraphRAG API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _map_insights(d):
    if not d:
        return {}
    money = lambda a: [{"victim": x["victim"], "industry": x.get("industry"), "usd": x.get("usd"), "raw": x.get("text")} for x in (a or [])]
    return {
        "total": d.get("total_victims"), "groupCount": d.get("group_count"),
        "countryCount": d.get("country_count"), "bySector": d.get("by_sector"),
        "byYear": d.get("by_year"), "topGroups": d.get("top_groups"),
        "topCountries": d.get("top_countries"), "heatmap": d.get("heatmap"),
        "coverage": d.get("coverage"), "financial": money(d.get("costliest")),
        "ransom": money(d.get("largest_ransoms")), "generated_at": d.get("generated_at"),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML.read_text(encoding="utf-8")


@app.get("/chat", response_class=HTMLResponse)
def chat():
    return CHAT.read_text(encoding="utf-8")


@app.get("/explorer.html", response_class=HTMLResponse)
def explorer():
    return HTML.read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"ok": True, "db": DB_NAME,
            "neo4j": engine.driver is not None,
            "mongo": engine.mongo is not None,
            "llm": bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/api/insights")
def insights():
    if engine.mongo is None:
        return JSONResponse({"error": "mongo not connected"}, status_code=503)
    return _map_insights(engine.mongo["insights"].find_one({"_id": "current"}))


@app.get("/api/industries")
def industries():
    if engine.mongo is None:
        return JSONResponse({"error": "mongo not connected"}, status_code=503)
    return list(engine.mongo["industries"].find())


@app.get("/api/synthesis")
def synthesis():
    if engine.mongo is None:
        return JSONResponse({"error": "mongo not connected"}, status_code=503)
    return engine.mongo["synthesis"].find_one({"_id": "current"}) or {}


class Ask(BaseModel):
    question: str
    synthesize: bool = True
    k: int = 6


@app.post("/api/ask")
def ask(body: Ask):
    if not body.question.strip():
        return JSONResponse({"error": "empty question"}, status_code=400)
    if engine.driver is None:
        return JSONResponse({"error": "graph backend not connected; check NEO4J_* env"}, status_code=503)
    try:
        return engine.answer(body.question, synthesize=body.synthesize, k=body.k)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
