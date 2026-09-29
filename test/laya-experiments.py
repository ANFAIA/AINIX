"""Which change to Laya actually helps? Each variant on the dev set (the 24 in
laya-eval.py, whose misses have been read) and the held-out set (written before
any of this, test/laya_heldout.py). A change is kept only if it helps held-out.

Variants toggle one thing at a time against the same runner:
  domain   candidate text includes the manifest's `domain` line, not only the card
  logprob  confidence from the model's own token probabilities, renormalised over
           the candidates, instead of the number it writes in its JSON
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import tomllib
import urllib.request
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents/lib"))
sys.path.insert(0, str(ROOT / "test"))
from laya_route import core, keyword_pick          # noqa: E402
from laya_heldout import HELDOUT                   # noqa: E402

DEV = import_module("laya-eval").CASES
SYSTEM = ("You route a user's request to exactly one agent. Read each agent's "
          "description and pick the one whose job the request is. Answer only "
          "with JSON: the agent's name and your confidence from 0 to 1.")


def candidates(domain: bool) -> list[dict]:
    acme = ROOT / "examples/acme/agents"
    peers = tomllib.loads((acme / "user/console/agent.toml").read_text(encoding="utf-8"))["agent"]["peers"]
    out = []
    for p in peers:
        m = tomllib.loads((acme / p / "agent.toml").read_text(encoding="utf-8"))
        desc = m["card"]["description"]
        if domain:
            desc = f"{m['agent']['domain']}. {desc}"
        out.append({"name": p, "description": desc, "skills": m["card"].get("skills", [])})
    return sorted(out, key=lambda c: c["name"])


def logprob_confidence(content: str, tokens: list[dict], pick: str, names: list[str]) -> float:
    """Share of probability the model put on `pick` at the first token where the
    candidate names diverge, renormalised over the candidates only. The logprobs
    llama.cpp reports are the model's own, before the grammar masks anything, so
    this is what it believed — not what the schema forced it to write."""
    key = '"agent": "'
    start = content.find(key)
    if start < 0:
        return 0.0
    start += len(key)
    prefix = __import__("os").path.commonprefix(names)
    div = start + len(prefix)
    off = 0
    for t in tokens:
        end = off + len(t["token"])
        if off <= div < end:
            rel = off - start                      # token's offset within the value
            mass = {n: 0.0 for n in names}
            for alt in t["top_logprobs"]:
                for n in names:
                    tail = (n + '"')[max(rel, 0):]
                    txt = alt["token"] if rel >= 0 else alt["token"][-rel:]
                    if txt and tail.startswith(txt):
                        mass[n] = max(mass[n], math.exp(alt["logprob"]))
            total = sum(mass.values())
            return mass[pick] / total if total > 0 else 0.0
        off = end
    return 0.0


def ask(url: str, request: str, cands: list[dict], conf_mode: str):
    names = [c["name"] for c in cands]
    listing = "\n".join(f"- {c['name']}: {c['description']}" for c in cands)
    schema = {"type": "object",
              "properties": {"agent": {"type": "string", "enum": names},
                             "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
              "required": ["agent", "confidence"]}
    body = {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Agents:\n{listing}\n\nRequest: {request}"}],
            "max_tokens": 48, "temperature": 0, "logprobs": True, "top_logprobs": 20,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "route", "schema": schema}}}
    r = json.load(urllib.request.urlopen(urllib.request.Request(
        url + "/v1/chat/completions", json.dumps(body).encode(),
        {"Content-Type": "application/json"}), timeout=120))["choices"][0]
    d = json.loads(r["message"]["content"])
    pick = d["agent"]
    if conf_mode == "self":
        return pick, float(d.get("confidence", 0))
    return pick, logprob_confidence(r["message"]["content"], r["logprobs"]["content"], pick, names)


def run(url, cases, domain, conf_mode, threshold=0.6):
    cands = candidates(domain)
    res = []
    for req, want in cases:
        t = time.monotonic()
        mp, conf = ask(url, req, cands, conf_mode)
        kw, score = keyword_pick(req, cands)
        pick, src = core.decide(mp, conf, kw, score, threshold, None)
        res.append({"want": want, "model": mp, "conf": conf, "final": pick,
                    "src": str(src), "ms": (time.monotonic() - t) * 1000})
    return res


def summarise(res):
    final = sum(r["final"] == r["want"] for r in res)
    model = sum(r["model"] == r["want"] for r in res)
    right = [r["conf"] for r in res if r["model"] == r["want"]]
    wrong = [r["conf"] for r in res if r["model"] != r["want"]]
    sep = (sum(right) / len(right) if right else 0) - (sum(wrong) / len(wrong) if wrong else 0)
    return final, model, sep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    print(f"{'variant':<28}{'dev':>10}{'held-out':>12}   model-only dev/held   conf separation dev/held")
    for domain in (False, True):
        for conf in ("self", "logprob"):
            name = f"{args.label}{'domain' if domain else 'card'}+{conf}"
            d = summarise(run(args.url, DEV, domain, conf))
            h = summarise(run(args.url, HELDOUT, domain, conf))
            print(f"{name:<28}{d[0]:>7}/24{h[0]:>9}/24   {d[1]:>6}/24 {h[1]:>3}/24"
                  f"          {d[2]:+.2f} / {h[2]:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
