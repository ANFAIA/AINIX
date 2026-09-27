"""Python twin of laya_core.mojo — kept line-for-line; test/policy-parity.py
checks they agree."""


def _words(text: str) -> list[str]:
    out, cur = [], ""
    for ch in text.lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            cur += ch
        else:
            if len(cur) >= 4:
                out.append(cur)
            cur = ""
    if len(cur) >= 4:
        out.append(cur)
    return out


def keyword_score(request, card_text) -> int:
    card = _words(card_text)
    score, seen = 0, []
    for w in _words(request):
        if w in seen:
            continue
        seen.append(w)
        for c in card:
            if c == w or (c.startswith(w) and len(w) >= 5) \
                    or (w.startswith(c) and len(c) >= 5):
                score += 1
                break
    return score


def decide(model_pick, model_conf, kw_pick, kw_score, threshold, only):
    if only is not None:
        return (only, "only")
    conf = float(model_conf) if model_pick is not None else 0.0
    score = int(kw_score) if kw_pick is not None else 0
    if model_pick is not None and kw_pick is not None and model_pick == kw_pick:
        return (model_pick, "agree")
    if model_pick is not None and conf >= float(threshold):
        return (model_pick, "model")
    if kw_pick is not None and score >= 1:
        return (kw_pick, "keyword")
    return (None, "none")


def engine() -> str:
    return "python"
