"""Candidate handling shared by Laya and agentd's fallback.

Order is part of the decision: candidates used to arrive in registration order,
so a keyword tie went to whichever agent happened to start first and the model
saw the list in a different order each run — the same eval scored 15 and then
14 with nothing changed. Candidates are sorted by name, and a tie at the top
score is ambiguity, not a choice.
"""
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
