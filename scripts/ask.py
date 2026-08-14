"""
ask.py — command-line front end to the GraphRAG engine (see rag_core.py).

The productionized interface is the HTTP API (api.py, POST /api/ask). This CLI
is the same engine for quick terminal use and testing.

Setup:
  pip install -r requirements.txt
  export NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
  export MONGODB_URI                      # enables the analytical lane
  python scripts/embed_graph.py          # once, builds the vector index

Usage:
  python scripts/ask.py "why is healthcare targeted so heavily?"
  python scripts/ask.py "top 5 groups in manufacturing"
  python scripts/ask.py "what's exposed in healthcare but not manufacturing?"
  python scripts/ask.py "why is healthcare unique?" --answer   # + LLM synthesis

By default it shows retrieved evidence only (no API). --answer adds LLM synthesis,
the only step that calls OpenAI/Anthropic.
"""

from __future__ import annotations

import sys

from rag_core import RagEngine


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit('usage: python scripts/ask.py "your question" [--answer] [--k=6]')
    q = " ".join(args)
    synth = "--answer" in sys.argv
    k = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--k=")), 6)

    engine = RagEngine()
    try:
        engine.connect()
    except Exception as e:
        raise SystemExit(str(e))

    res = engine.answer(q, synthesize=synth, k=k)
    print(f"[{res['lane']}]\n")
    for e in res["evidence"]:
        head = f"({e['type']}" + (f", score {e['score']}" if "score" in e else "") + ")"
        print(f"  {head} {str(e.get('text',''))[:200]}")
        if e.get("linked"):
            print(f"      linked: {', '.join(str(x) for x in e['linked'])}")
        print()
    if synth:
        print("-" * 60)
        print(res["answer"] or "(set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable --answer)")
    engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
