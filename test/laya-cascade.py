"""Laya as a cascade: the small model decides; when it is unsure, ask a bigger one.

Confidence is the small model's own token probability over the candidates
(laya-experiments.py: it separates right from wrong, +0.42 on held-out, where
the number the model writes in its JSON does not, +0.07). Keywords are not in
the loop — the experiments showed they are worse than the model even when the
model is unsure. Each request is asked of both models once; thresholds are then
swept offline over the recorded answers.
"""
from __future__ import annotations

import argparse
import sys
import time
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
X = import_module("laya-experiments")


def record(url, cases, domain):
    cands = X.candidates(domain)
    out = []
    for req, want in cases:
        t = time.monotonic()
        pick, conf = X.ask(url, req, cands, "logprob")
        out.append((want, pick, conf, (time.monotonic() - t) * 1000))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--small", required=True)
    ap.add_argument("--big", required=True)
    ap.add_argument("--domain", action="store_true")
    a = ap.parse_args()
    for name, cases in (("dev", X.DEV), ("held-out", X.HELDOUT)):
        s = record(a.small, cases, a.domain)
        b = record(a.big, cases, a.domain)
        print(f"\n{name}: small alone {sum(w == p for w, p, _, _ in s)}/24 "
              f"({sum(m for *_, m in s) / 24:.0f} ms avg), "
              f"big alone {sum(w == p for w, p, _, _ in b)}/24 "
              f"({sum(m for *_, m in b) / 24:.0f} ms avg)")
        for tau in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
            ok = esc = ms = 0
            for (w, sp, sc, sm), (_, bp, _, bm) in zip(s, b, strict=True):
                ms += sm
                if sc < tau:
                    esc += 1
                    ms += bm
                    ok += bp == w
                else:
                    ok += sp == w
            print(f"   cascade tau={tau:<4}  {ok}/24   escalated {esc:>2}/24   {ms / 24:>5.0f} ms avg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
