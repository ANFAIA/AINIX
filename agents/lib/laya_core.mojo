# Laya's deterministic half: score candidates, and decide whose choice stands.
#
# Laya is the decision layer — the ART/JVM of AINIX. For each request it picks
# which agent (and which of its skills) should answer, from the candidates
# agentd says the caller may use. The small model makes the first call; this
# module is everything around it that must not depend on a model: a keyword
# score that works with no model at all, and the rule that decides between the
# model's pick and the score's when they disagree or the model is unsure.
#
#   mojo build --emit shared-lib agents/lib/laya_core.mojo -o agents/lib/laya_core.so

from std.os import abort
from std.python import Python, PythonObject
from std.python.bindings import PythonModuleBuilder


def _words(text: String) -> List[String]:
    """Lowercase words of four or more letters. Short words ("the", "list",
    "a") match everything and decide nothing."""
    var out = List[String]()
    var cur = String("")
    var low = text.lower()
    var bytes = low.as_bytes()
    for i in range(low.byte_length()):
        var c = Int(bytes[i])
        if (c >= ord("a") and c <= ord("z")) or (c >= ord("0") and c <= ord("9")):
            cur += chr(c)
        else:
            if cur.byte_length() >= 4:
                out.append(cur)
            cur = String("")
    if cur.byte_length() >= 4:
        out.append(cur)
    return out^


def keyword_score(request: PythonObject, card_text: PythonObject) raises -> PythonObject:
    """How many distinct long words of the request appear in the card."""
    var req = _words(String(py=request))
    var card = _words(String(py=card_text))
    var score = 0
    var seen = List[String]()
    for w in req:
        var dup = False
        for s in seen:
            if s == w:
                dup = True
        if dup:
            continue
        seen.append(w)
        for c in card:
            if c == w or (c.startswith(w) and w.byte_length() >= 5) \
                    or (w.startswith(c) and c.byte_length() >= 5):
                score += 1
                break
    return PythonObject(score)


def decide(
    model_pick: PythonObject, model_conf: PythonObject,
    kw_pick: PythonObject, kw_score: PythonObject,
    threshold: PythonObject,
) raises -> PythonObject:
    """Whose choice stands. Returns (pick, source) with source one of
    "model", "agree", "keyword", "none".

    - model and keyword agree            -> that pick, "agree"
    - model confident (>= threshold)     -> model's pick, "model"
    - model unsure, keyword has evidence -> keyword's pick, "keyword"
    - neither                            -> None, "none": say so, do not guess
    A model pick of None (no model, or it failed) counts as unsure."""
    var conf = Float64(py=model_conf) if model_pick is not None else 0.0
    var score = Int(py=kw_score) if kw_pick is not None else 0
    var t = Float64(py=threshold)
    var none = PythonObject(None)
    if model_pick is not None and kw_pick is not None \
            and String(py=model_pick) == String(py=kw_pick):
        return Python.tuple(model_pick, PythonObject("agree"))
    if model_pick is not None and conf >= t:
        return Python.tuple(model_pick, PythonObject("model"))
    if kw_pick is not None and score >= 1:
        return Python.tuple(kw_pick, PythonObject("keyword"))
    return Python.tuple(none, PythonObject("none"))


def engine() raises -> PythonObject:
    return PythonObject("mojo")


@export
def PyInit_laya_core() abi("C") -> PythonObject:
    try:
        var m = PythonModuleBuilder("laya_core")
        m.def_function[keyword_score]("keyword_score")
        m.def_function[decide]("decide")
        m.def_function[engine]("engine")
        return m.finalize()
    except e:
        abort(String("failed to create laya_core: ", e))
