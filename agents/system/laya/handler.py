"""Laya: decide which agent answers a request.

How the small model is used, and why each constraint is there:

- **One constrained choice.** The answer must match a JSON schema whose `agent`
  field is an enum of the candidates' names. A 0.8B model asked in free text
  will sooner or later name an agent that does not exist; with the grammar it
  cannot.
- **Temperature 0, thinking off, 48 tokens.** A routing decision is a lookup,
  not an essay. Thinking would spend the budget in reasoning and return
  nothing — the empty-answer failure this repo has already paid for.
- **Its confidence is advisory.** laya_core.decide() weighs it against a
  model-free keyword score; agreement wins outright, a confident model wins, an
  unsure one yields to keyword evidence, and with neither Laya says no one here
  can help instead of guessing.

The deterministic half is Mojo (laya_core); the Python twin stands in where it
is not built.
"""
from __future__ import annotations

import json
import os
import time

from laya_route import core, keyword_pick, ordered

THRESHOLD = float(os.environ.get("LAYA_THRESHOLD", "0.6"))
MODEL = "qwen3.5-0.8b"

SYSTEM = ("You route a user's request to exactly one agent. Read each agent's "
          "description and pick the one whose job the request is. Answer only "
          "with JSON: the agent's name and your confidence from 0 to 1.")


def model_pick(agent, request: str, candidates: list[dict]) -> tuple[str | None, float]:
    names = [c["name"] for c in candidates]
    listing = "\n".join(f"- {c['name']}: {c.get('description', '')}" for c in candidates)
    schema = {"type": "object",
              "properties": {"agent": {"type": "string", "enum": names},
                             "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
              "required": ["agent", "confidence"]}
    try:
        raw = agent.model(MODEL).complete(
            f"Agents:\n{listing}\n\nRequest: {request}", system=SYSTEM,
            thinking=False, max_tokens=48, temperature=0,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "route", "schema": schema}})
        d = json.loads(raw)
        return (d["agent"] if d.get("agent") in names else None,
                float(d.get("confidence", 0)))
    except Exception:
        return None, 0.0          # no model, or it failed: Laya still decides


def handle(agent, task) -> dict:
    t0 = time.monotonic()
    req = task["input"]["request"]
    cands = ordered(task["input"]["candidates"])
    only = cands[0]["name"] if len(cands) == 1 else None
    kw, kw_score = keyword_pick(req, cands)
    # One candidate: no model call at all — there is nothing to choose.
    mp, conf = (None, 0.0) if only else model_pick(agent, req, cands)
    pick, source = core.decide(mp, conf, kw, kw_score, THRESHOLD, only)
    skill = next((c.get("skills", [""])[0] for c in cands if c["name"] == pick), None)
    return {"agent": pick, "skill": skill, "source": str(source),
            "model_pick": mp, "confidence": round(conf, 2),
            "keyword_pick": kw, "keyword_score": kw_score,
            "engine": str(core.engine()),
            "ms": round((time.monotonic() - t0) * 1000)}
