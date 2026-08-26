#!/usr/bin/env python3
"""Generate synthetic AINIX_NEO_terminal data verified inside a Docker container.

Pipeline (verification-gated generation — an RLVR-style reward loop):

  1. PROPOSE   teacher model writes candidate examples grounded in
               training/corpus/terminal/*.md (the same corpus generate.py uses).
  2. REWARD    every candidate that claims a shell command is executed inside a
               disposable Linux container: `sh -n` first, then a real run with
               a timeout and resource caps. reward=1 iff it parses and exits 0.
  3. KEEP      only reward=1 records are written. Everything else is discarded,
               never repaired — same policy as verify.py.

The Docker exec function (`docker_reward`) is deliberately standalone so the
same environment can be plugged into GRPOTrainer later as a reward function
for actual reinforcement learning on top of this data.

Stdlib only. Needs a running Docker daemon and OPENROUTER_API_KEY.

    export OPENROUTER_API_KEY=...
    python3 training/synthesize_docker.py --per-doc 12 \
        --out training/data/AINIX_NEO_terminal.jsonl
"""

from __future__ import annotations

import argparse
import atexit
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate import INSTRUCTIONS, ask, chunk, load_teacher, parse_pairs

ROOT = Path(__file__).resolve().parent.parent

IMAGE = "ainix/terminal-sandbox"
BASE_IMAGE = "debian:stable-slim"
TIMEOUT = 20          # seconds per exec
MEM = "256m"
CPUS = "1.0"

# Commands that must never run even once, even in a throwaway container.
HARD_REFUSE = (
    "rm -rf /", "mkfs", ":(){ :|:& };:", "dd if=/dev/zero of=/dev/",
    "chmod -r 777 /", "> /dev/sda", "shutdown", "reboot",
)

PROPOSAL_SCHEMA = """
Return a JSON array. Each element:
{"user": "...", "assistant": "..."} where assistant is EITHER the JSON
command contract {"command":..., "explain":..., "mutates":...} OR plain prose
(for questions/refusals). No markdown fence, no prose outside the array.
"""


# --------------------------------------------------------------------------
# Reward environment
# --------------------------------------------------------------------------


def _exec(container: str, argv: list[str]) -> tuple[int, str]:
    """Run argv inside the running sandbox container. Returns (exit, output)."""
    cmd = ["docker", "exec", container] + argv
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        return p.returncode, (p.stdout + p.stderr)[:2000]
    except subprocess.TimeoutExpired:
        return 124, "timeout"


SEED = (
    "mkdir -p ~/Documents /srv/app/data notes /var/log && "
    "touch deploy.sh notes/meeting.txt /var/log/syslog && "
    "echo 'hello' > notes/meeting.txt"
)


def start_sandbox() -> str:
    """Start one disposable container and seed fixture files.

    Commands the teacher invents often reference plausible files; seeding a
    small fixture tree keeps those from being rejected for missing files
    while still catching genuinely broken commands."""
    p = subprocess.run(
        ["docker", "run", "-d", "--network", "none",
         "--memory", MEM, "--cpus", CPUS, "--pids-limit", "64",
         IMAGE, "sleep", "infinity"],
        capture_output=True, text=True, check=True)
    cid = p.stdout.strip()
    _exec(cid, ["sh", "-c", SEED])
    return cid


def stop_sandbox(container: str) -> None:
    subprocess.run(["docker", "rm", "-f", container],
                   capture_output=True, text=True)


def docker_reward(container: str, command: str) -> dict:
    """Reward function: 1 iff command parses AND runs clean in the sandbox."""
    if any(bad in command.lower() for bad in HARD_REFUSE):
        return {"reward": 0, "reason": "hard-refuse pattern"}
    rc, out = _exec(container, ["sh", "-n", "-c", command])
    if rc != 0:
        return {"reward": 0, "reason": f"syntax (sh -n exit {rc}): {out}"}
    rc, out = _exec(container, ["sh", "-c", command])
    return {"reward": int(rc == 0),
            "reason": "" if rc == 0 else f"exec exit {rc}: {out}",
            "exit_code": rc}


DOCKERFILE = f"""FROM {BASE_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends \\
    sudo iproute2 iputils-ping openssh-client wget curl procps psmisc \\
    net-tools findutils tar gzip zip unzip file less logrotate \\
 && rm -rf /var/lib/apt/lists/*
"""


def ensure_image() -> None:
    p = subprocess.run(["docker", "image", "inspect", IMAGE],
                       capture_output=True)
    if p.returncode != 0:
        print(f"building {IMAGE} (one-time) ...")
        with tempfile.TemporaryDirectory() as td:
            ctx = Path(td) / "Dockerfile"
            ctx.write_text(DOCKERFILE)
            subprocess.run(["docker", "build", "-t", IMAGE, td], check=True)


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--teacher", default="remote.ox-alpha-free")
    ap.add_argument("--out", default="training/data/AINIX_NEO_terminal.jsonl")
    ap.add_argument("--corpus", default="training/corpus/terminal/*.md")
    ap.add_argument("--per-doc", type=int, default=12)
    ap.add_argument("--limit", type=int, help="stop after N source chunks")
    args = ap.parse_args()

    teacher = load_teacher(args.teacher)
    ensure_image()
    sandbox = start_sandbox()
    atexit.register(stop_sandbox, sandbox)
    print(f"sandbox {sandbox[:12]} | image {IMAGE}")

    docs = sorted(ROOT.glob(args.corpus))
    units = [(d.name, i, t) for d in docs
             for i, t in enumerate(chunk(d.read_text(errors="replace")))]
    if args.limit:
        units = units[: args.limit]
    print(f"{len(units)} chunks from {len(docs)} docs | image {IMAGE}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    kept = rejected = 0
    try:
        with out.open("a") as fh:
            for name, idx, text in units:
                n = max(4, args.per_doc // 2)
                prompt = (
                    INSTRUCTIONS["terminal"].format(n=n)
                    + "\nAlso include 2 plain Q&A pairs about the reference content."
                    + PROPOSAL_SCHEMA
                    + f"\n\n--- {name} (chunk {idx}) ---\n{text}\n"
                )
                print(f"[propose] {name}#{idx}")
                try:
                    candidates = parse_pairs(ask(teacher, prompt))
                except Exception as e:
                    print(f"  ! teacher failed: {type(e).__name__}: {e}",
                          file=sys.stderr)
                    continue
                print(f"  {len(candidates)} candidates")

                for c in candidates:
                    raw = c["assistant"]
                    # Teacher may emit the contract as an object or a JSON string.
                    parsed = raw if isinstance(raw, dict) else None
                    body = raw.strip() if isinstance(raw, str) else json.dumps(raw)
                    cmd = None
                    if parsed and "command" in parsed:
                        cmd = parsed.get("command")
                    elif isinstance(raw, str) and body.startswith("{"):
                        try:
                            cmd = json.loads(body).get("command")
                        except json.JSONDecodeError:
                            pass
                    if cmd is None:
                        reward = {"reward": 1, "reason": ""}
                    else:
                        reward = docker_reward(sandbox, str(cmd))
                        note = f"  <- {reward['reason'][:60]}" if reward.get("reason") else ""
                        print(f"  [{reward['reward']}] {str(cmd)[:70]}{note}")
                    if reward["reward"] != 1:
                        rejected += 1
                        continue
                    fh.write(json.dumps({
                        "messages": [
                            {"role": "system", "content": "You are the AINIX assistant."},
                            {"role": "user", "content": c["user"]},
                            {"role": "assistant", "content": body},
                        ],
                        "meta": {"source": f"synth:{name}", "chunk": idx,
                                 "task": "terminal", "teacher": teacher["model"],
                                 "verified": True, "reward": 1},
                    }) + "\n")
                    fh.flush()
                    kept += 1

    finally:
        stop_sandbox(sandbox)

    total = kept + rejected
    print(f"\nkept {kept}, rejected {rejected} "
          f"(discard rate {rejected / max(1, total):.0%})")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
