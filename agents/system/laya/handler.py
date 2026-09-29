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

from laya_route import core, keyword_pick, logprob_confidence, ordered

# Below this, the small model's pick is not trusted on its own and Laya asks
# the bigger model it holds a grant for. Swept on dev and held-out
# (test/laya-cascade.py): at 0.7 the cascade reached 23/24 and 24/24 while
# escalating 29% and 54% of requests.
ESCALATE = float(os.environ.get("LAYA_ESCALATE", "0.7"))
THRESHOLD = ESCALATE

SYSTEM = ("You route a user's request to exactly one agent. Read each agent's "
          "description and pick the one whose job the request is. Answer only "
          "with JSON: the agent's name and your confidence from 0 to 1.")


def _listing(candidates: list[dict]) -> str:
    return "\n".join(f"- {c['name']}: {c.get('description', '')}" for c in candidates)


def model_pick(agent, model: str, request: str,
               candidates: list[dict]) -> tuple[str | None, float, str | None]:
    """One schema-constrained choice. Confidence is read from the model's token
    probabilities over the candidates, not from the number it writes: the
    written one did not separate right answers from wrong ones."""
    names = [c["name"] for c in candidates]
    schema = {"type": "object",
              "properties": {"agent": {"type": "string", "enum": names},
                             "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
              "required": ["agent", "confidence"]}
    try:
        m = agent.model(model)
        raw, tokens = m.complete_with_logprobs(
            f"Agents:\n{_listing(candidates)}\n\nRequest: {request}", system=SYSTEM,
            thinking=False, max_tokens=48, temperature=0,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "route", "schema": schema}})
        pick = json.loads(raw).get("agent")
        if pick not in names:
            return None, 0.0, None
        return pick, logprob_confidence(raw, tokens, pick, names), getattr(m, "served", None)
    except Exception:
        return None, 0.0, None    # no model, or it failed: Laya still decides


def handle(agent, task) -> dict:
    t0 = time.monotonic()
    req = task["input"]["request"]
    cands = ordered(task["input"]["candidates"])
    only = cands[0]["name"] if len(cands) == 1 else None
    kw, kw_score = keyword_pick(req, cands)
    # The models Laya holds grants for, smallest first: the first decides, the
    # next is asked only when the first is unsure.
    models = agent.manifest["agent"].get("models", [])
    mp, conf, used, escalated = None, 0.0, None, False
    if not only and models:
        used = models[0]
        mp, conf, served = model_pick(agent, used, req, cands)
        if (mp is None or conf < ESCALATE) and len(models) > 1:
            big, big_conf, big_served = model_pick(agent, models[1], req, cands)
            # Only a different model is an escalation. On a machine with one
            # runner both names reach the same weights, and trusting the second
            # answer as "the big model" would be a lie in the audit log.
            if big is not None and not (served and big_served == served):
                mp, conf, used, escalated = big, max(big_conf, ESCALATE), models[1], True
    pick, source = core.decide(mp, conf, kw, kw_score, THRESHOLD, only)
    skill = next((c.get("skills", [""])[0] for c in cands if c["name"] == pick), None)
    return {"agent": pick, "skill": skill, "source": str(source),
            "model_pick": mp, "confidence": round(conf, 2),
            "model": used, "escalated": escalated,
            "keyword_pick": kw, "keyword_score": kw_score,
            "engine": str(core.engine()),
            "ms": round((time.monotonic() - t0) * 1000)}
