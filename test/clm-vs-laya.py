"""CLM against Laya on the same routing task.

The same 24 labelled requests and the same six candidate agents as
test/laya-eval.py (ACME, from the console's point of view), scored the same way.
Both are called in-process against their model servers, so the numbers compare
the deciders, not the broker around them.

  CLM   Contrastive-LM/CLM-v0.1-8B: a 75 MB contrastive head over Qwen3-8B
        last-token embeddings. One Choice question, criteria = agent cards.
  Laya  Qwen3.5-0.8B making one JSON-schema-constrained choice, merged with a
        model-free keyword score by laya_core.

Caveats stated up front: CLM's reference setup is vLLM on a GPU in bf16; here the
encoder is llama.cpp, Q8_0, on CPU inside Docker — so its latency is not its
best case, and the embeddings are close to, not identical with, the ones its head
was trained on.

    python test/clm-vs-laya.py --emb http://127.0.0.1:8097 --llm http://127.0.0.1:8090
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents/lib"))
sys.path.insert(0, str(ROOT / "agents/system/laya"))
sys.path.insert(0, str(ROOT / "test"))

from importlib import import_module  # noqa: E402

CASES = import_module("laya-eval").CASES


def cards() -> list[dict]:
    peers = tomllib.loads((ROOT / "examples/acme/agents/user/console/agent.toml")
                          .read_text(encoding="utf-8"))["agent"]["peers"]
    out = []
    for p in peers:
        m = tomllib.loads((ROOT / "examples/acme/agents" / p / "agent.toml")
                          .read_text(encoding="utf-8"))
        out.append({"name": p, "description": m["card"]["description"],
                    "skills": m["card"].get("skills", [])})
    return sorted(out, key=lambda c: c["name"])


class RunnerModel:
    """Just enough of ainix_agent's Model for Laya's handler, pointed at a
    runner directly instead of through agentd."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def complete(self, prompt, system="", **kw):
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "max_tokens": kw.get("max_tokens", 48),
                "temperature": kw.get("temperature", 0),
                "chat_template_kwargs": {"enable_thinking": bool(kw.get("thinking"))}}
        if kw.get("response_format"):
            body["response_format"] = kw["response_format"]
        r = urllib.request.urlopen(urllib.request.Request(
            self.url + "/v1/chat/completions", json.dumps(body).encode(),
            {"Content-Type": "application/json"}), timeout=120)
        return json.load(r)["choices"][0]["message"]["content"]


class Stub:
    def __init__(self, url):
        self._m = RunnerModel(url)

    def model(self, _name):
        return self._m


def run_laya(llm: str, cands: list[dict]):
    import handler
    agent = Stub(llm)
    got, ms = [], []
    for req, _ in CASES:
        t = time.monotonic()
        d = handler.handle(agent, {"input": {"request": req, "candidates": cands}})
        ms.append((time.monotonic() - t) * 1000)
        got.append((d["agent"], d["source"]))
    return got, ms


def run_clm(emb: str, cands: list[dict]):
    from clm import Engine
    from clm.heads import download
    # The Engine does not fetch the head itself (only clm-serve does); pass it,
    # or answer() finds only the raw no-head ablation.
    engine = Engine(emb_url=emb.rstrip("/") + "/v1/embeddings", checkpoint=download())
    q = {"type": "choice", "instructions": "Which agent should handle this request?",
         "criteria": {c["name"]: c["description"] for c in cands}}
    engine.answer("warm up", {"route": q})           # embed the options once
    got, ms = [], []
    for req, _ in CASES:
        t = time.monotonic()
        a = engine.answer(req, {"route": q})["answers"]["route"]
        ms.append((time.monotonic() - t) * 1000)
        probs = a.get("probabilities", {})
        got.append((a.get("choice"), f"p={max(probs.values()):.2f}" if probs else ""))
        PROBS.append(max(probs.values()) if probs else 0.0)
    return got, ms


PROBS: list[float] = []


def run_hybrid(clm_got, clm_ms, cands):
    """CLM as Laya's chooser instead of the LLM: its pick and probability go
    through the same laya_core.decide() merge with the keyword score."""
    from laya_route import core, keyword_pick
    got = []
    for (pick, _), p, (req, _) in zip(clm_got, PROBS, CASES, strict=True):
        kw, score = keyword_pick(req, cands)
        final, source = core.decide(pick, p, kw, score, 0.6, None)
        got.append((final, str(source)))
    return got, clm_ms


def report(label, got, ms):
    ok = sum(1 for (g, _), (_, want) in zip(got, CASES, strict=True) if g == want)
    print(f"\n{label}: {ok}/{len(CASES)} correct, median {statistics.median(ms):.0f} ms, "
          f"p90 {sorted(ms)[int(len(ms) * 0.9)]:.0f} ms")
    for (g, how), (req, want) in zip(got, CASES, strict=True):
        if g != want:
            print(f"   miss  {req[:50]:<50} want {want:<18} got {str(g):<18} {how}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True, help="llama.cpp /v1/embeddings server for Qwen3-8B")
    ap.add_argument("--llm", required=True, help="runner serving Qwen3.5-0.8B for Laya")
    args = ap.parse_args()
    cands = cards()
    print(f"{len(CASES)} requests, {len(cands)} candidates: "
          f"{', '.join(c['name'].split('/')[1] for c in cands)}")
    c_got, c_ms = run_clm(args.emb, cands)
    l_got, l_ms = run_laya(args.llm, cands)
    h_got, h_ms = run_hybrid(c_got, c_ms, cands)
    c = report("CLM-v0.1-8B (Qwen3-8B Q8_0 embeddings, Metal)", c_got, c_ms)
    l = report("Laya (Qwen3.5-0.8B constrained + keyword)", l_got, l_ms)
    h = report("Laya with CLM as its chooser (CLM + keyword)", h_got, h_ms)
    both = sum(1 for (a, _), (b, _), (_, w) in zip(c_got, l_got, CASES, strict=True)
               if a == w or b == w)
    print(f"\nCLM {c}/24   Laya {l}/24   Laya+CLM {h}/24   CLM-or-Laya right: {both}/24")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
