"""Candidate handling shared by Laya and agentd's fallback.

Order is part of the decision: candidates used to arrive in registration order,
so a keyword tie went to whichever agent happened to start first and the model
saw the list in a different order each run — the same eval scored 15 and then
14 with nothing changed. Candidates are sorted by name, and a tie at the top
score is ambiguity, not a choice.
"""
import math
import os

try:
    import laya_core as core
except ImportError:
    import laya_py as core


def ordered(cands: list[dict]) -> list[dict]:
    return sorted(cands, key=lambda c: c["name"])


def keyword_pick(request: str, cands: list[dict]) -> tuple[str | None, int]:
    scores = [(int(core.keyword_score(
        request, f"{c.get('description', '')} {' '.join(c.get('skills', []))}")),
        c["name"]) for c in ordered(cands)]
    top = max((s for s, _ in scores), default=0)
    leaders = [n for s, n in scores if s == top and s > 0]
    if len(leaders) != 1:
        return None, 0            # nothing, or a tie: no keyword evidence
    return leaders[0], top


def logprob_confidence(content: str, tokens: list[dict], pick: str,
                       names: list[str]) -> float:
    """Share of probability the model put on `pick` at the first token where
    the candidate names diverge, renormalised over the candidates.

    llama.cpp reports the model's own logprobs, before the grammar masks
    anything, so this is what the model believed rather than what the schema
    forced it to write. Measured against the number it writes in its JSON: that
    one separates right from wrong answers by +0.07, this one by +0.42."""
    key = '"agent": "'
    start = content.find(key)
    if start < 0 or not tokens:
        return 0.0
    start += len(key)
    div = start + len(os.path.commonprefix(names))
    off = 0
    for t in tokens:
        end = off + len(t["token"])
        if off <= div < end:
            rel = off - start
            mass = dict.fromkeys(names, 0.0)
            for alt in t.get("top_logprobs", []):
                txt = alt["token"] if rel >= 0 else alt["token"][-rel:]
                for n in names:
                    if txt and (n + '"')[max(rel, 0):].startswith(txt):
                        mass[n] = max(mass[n], math.exp(alt["logprob"]))
            total = sum(mass.values())
            return mass.get(pick, 0.0) / total if total > 0 else 0.0
        off = end
    return 0.0
