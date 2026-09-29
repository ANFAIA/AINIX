"""Does Laya route requests to the right agent? Measured, not assumed.

Brings up the ACME deployment — agentd, the six app agents the console may use
(as stubs that report who they are), and Laya — then sends 24 labelled requests
through the console's `ask`. Run twice: with Laya and its small model, and with
Laya stopped, which leaves agentd's model-free keyword fallback. Requests are
phrased the way a person would, not by copying words off the agents' cards, so
the keyword score gets no free help.

    python3 test/laya-eval.py --runner http://127.0.0.1:8090
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACME = ROOT / "examples/acme"
sys.path.insert(0, str(ROOT / "agents/lib"))
sys.path.insert(0, str(ROOT / "test"))

CASES = [
    ("Write something for our LinkedIn about the new export feature", "app/social-media"),
    ("Draft a tweet announcing we're at the conference next week", "app/social-media"),
    ("Can you schedule a post for Friday morning on X?", "app/social-media"),
    ("Give me three short captions for the product launch", "app/social-media"),
    ("What's worth sharing from this week's industry news?", "app/article-scout"),
    ("Find a good blog post about AI inference we could repost", "app/article-scout"),
    ("Is this TechCrunch piece relevant enough to share with our followers?", "app/article-scout"),
    ("Look for recent articles on edge computing trends", "app/article-scout"),
    ("The pricing page still says three tiers, fix the copy", "app/web-content"),
    ("Update the About us page with the new office address", "app/web-content"),
    ("Our homepage headline sounds dated, rewrite it", "app/web-content"),
    ("Check that the website doesn't promise features we removed", "app/web-content"),
    ("What did our main rival ship this quarter?", "app/competitors"),
    ("Did Globex change their prices recently?", "app/competitors"),
    ("How does our onboarding compare with the other vendors'?", "app/competitors"),
    ("Who else is going after mid-size manufacturers like we are?", "app/competitors"),
    ("How big is the market for on-prem AI appliances?", "app/market"),
    ("Is demand for local inference growing or flat?", "app/market"),
    ("Which segments should we target next year?", "app/market"),
    ("Estimate how many companies could buy this in Europe", "app/market"),
    ("Find the signed contract with our biggest customer", "app/librarian"),
    ("Where is the latest version of the security policy document?", "app/librarian"),
    ("Pull up the board deck from last month", "app/librarian"),
    ("Who is allowed to read the HR handbook?", "app/librarian"),
]

STUB = """
import sys
sys.path.insert(0, {lib!r})
from ainix_agent import Agent
a = Agent.from_manifest({manifest!r})
while True:
    t = a.next_task()
    if t is None: break
    a.reply(t, {{"handled_by": a.name}})
"""


def wait_socket(path: str) -> None:
    for _ in range(100):
        try:
            s = socket.socket(socket.AF_UNIX); s.connect(path); s.close(); return
        except OSError:
            time.sleep(0.1)
    raise SystemExit("agentd did not come up")


def run(label: str, with_laya: bool, env: dict, cases=None) -> list[bool]:
    cases = cases or CASES
    from ainix_agent import Agent
    procs = []
    for n in {e for _, e in cases}:
        m = ACME / "agents" / n / "agent.toml"
        procs.append(subprocess.Popen([sys.executable, "-c", STUB.format(
            lib=str(ROOT / "agents/lib"), manifest=str(m))], env=env))
    if with_laya:
        procs.append(subprocess.Popen(
            [sys.executable, str(ROOT / "agents/lib/run_agent.py"),
             str(ACME / "agents/system/laya")], env=env,
            stdout=subprocess.DEVNULL))
    time.sleep(1.5)
    console = Agent.from_manifest(str(ACME / "agents/user/console/agent.toml"))
    hits, rows, ms = [], [], []
    esc = 0
    for req, want in cases:
        try:
            r = console.ask(req, timeout=60)
            got, d = r["routed_to"], r["decision"]
            how = d.get("source") + (" [8b]" if d.get("escalated") else "")
            esc += bool(d.get("escalated"))
            if "ms" in d:
                ms.append(d["ms"])
        except Exception as e:
            got, how = None, f"refused: {e}"[:40]
        hits.append(got == want)
        rows.append((got == want, req, want, got, how))
    for p in procs:
        p.terminate()
    ok = sum(hits)
    lat = f", decision median {sorted(ms)[len(ms) // 2]} ms" if ms else ""
    print(f"\n{label}: {ok}/{len(cases)} routed correctly{lat}"
          + (f", escalated {esc}/{len(cases)}" if with_laya else ""))
    for good, req, want, got, how in rows:
        if not good:
            print(f"   miss  {req[:52]:<52} want {want:<18} got {str(got):<18} {how}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", required=True)
    ap.add_argument("--runners", default="{}",
                    help='JSON model->url, e.g. {"qwen3-8b": "http://127.0.0.1:8099"}')
    args = ap.parse_args()
    sock = os.path.join(tempfile.gettempdir(), f"laya-eval-{os.getpid()}.sock")
    env = dict(os.environ, AINIX_SOCK=sock, AINIX_ROOT=str(ACME),
               AINIX_RUNNER=args.runner, AINIX_RUNNERS=args.runners, PYTHONPATH=str(ROOT / "agents/lib"))
    os.environ.update(env)
    agentd = subprocess.Popen([sys.executable, str(ROOT / "agents/system/agentd/agentd.py")],
                              env=env, stderr=open(sock + ".log", "w"))
    try:
        wait_socket(sock)
        from laya_heldout import HELDOUT
        kw = run("keyword only (Laya not running), dev", False, env)
        ly = run("Laya, dev", True, env)
        ho = run("Laya, held-out", True, env, HELDOUT)
    finally:
        agentd.terminate()
    print(f"\nkeyword {sum(kw)}/{len(kw)}  ->  Laya dev {sum(ly)}/{len(ly)}, "
          f"held-out {sum(ho)}/{len(ho)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
