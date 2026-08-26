"""Validate a fine-tuned adapter against a held-out benchmark.

The model was trained on all 2507 records with no split, so nothing in
`training/data/` can measure it — every prompt there is contaminated. This
uses the **test split of NL2Bash** (`dilkushsingh/NL2Bash`, MIT), a benchmark
from a source that was not in training at all, and drops any prompt that
overlaps the training data anyway.

Four things are measured, weakest evidence to strongest:

  answers      did it produce a command at all, rather than refusing
  contract     did it use the {command, explain, mutates} shape that
               app/shell-expert actually parses
  runs         does the command execute cleanly in the sandbox — the same
               reward environment synthesize_docker.py uses
  matches      does it use the same base utility as the reference answer

`runs` is not correctness: `ls | sort -r` runs fine and still answers the
wrong question. `matches` is a weak proxy. `correct` is the real measure —
it compares effects, and is the same signal the improvement loop trains on.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "training"))

SYSTEM = ("You are the AINIX assistant. Answer with ONLY a JSON object: "
          '{"command":..., "explain":..., "mutates":true|false}.')

REFUSAL = re.compile(r"\b(I (do not|don't|cannot|can't)|as an AI|I'm unable)\b", re.I)


def load_eval(csv_path: Path, seen: set[str], limit: int) -> list[dict]:
    rows = []
    with csv_path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            nl = (r.get("nl") or "").strip()
            if not nl or nl.lower() in seen:
                continue
            rows.append({"nl": nl, "ref": (r.get("bash") or "").strip()})
            if len(rows) >= limit:
                break
    return rows


def training_prompts() -> set[str]:
    p = ROOT / "training/data/AINIX_NEO_terminal.jsonl"
    out = set()
    for line in p.read_text().splitlines():
        try:
            out.add(json.loads(line)["messages"][1]["content"].strip().lower())
        except Exception:
            continue
    return out


def extract(text: str) -> tuple[str | None, bool]:
    """Returns (command, used_contract)."""
    m = re.search(r"\{[^{}]*\"command\"[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            c = json.loads(m.group(0)).get("command")
            if isinstance(c, str) and c.strip():
                return c.strip(), True
        except json.JSONDecodeError:
            pass
    # Not the contract. Take the first plausible command line so that format
    # failure and inability-to-answer stay separate measurements.
    for raw in text.splitlines():
        line = raw.strip().strip("`").removeprefix("$ ").strip()
        line = re.sub(r"^</?reply>$", "", line).strip()
        if line and not line.startswith(("<", "#", "{", "}")) and " " in line or (
                line and re.match(r"^[a-z][\w.-]*$", line)):
            return line, False
    return None, False


def sandbox(cmds: list[str]) -> list[bool]:
    """Run each command in one throwaway container. Same environment the
    reward loop uses, so a pass here means the same thing it means there."""
    script = "\n".join(
        f"sh -n -c {json.dumps(c)} >/dev/null 2>&1 && sh -c {json.dumps(c)} "
        f">/dev/null 2>&1 && echo OK || echo NO" for c in cmds)
    p = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "512m",
         "--pids-limit", "128", "debian:stable-slim", "sh", "-c",
         "mkdir -p ~/Documents /srv/app/data notes /var/log && "
         "touch deploy.sh notes/meeting.txt /var/log/syslog file.txt && "
         "cat > /tmp/s.sh && sh /tmp/s.sh"],
        input=script, capture_output=True, text=True, timeout=600)
    return [l == "OK" for l in p.stdout.strip().splitlines()]


def base_util(cmd: str) -> str:
    for tok in cmd.split():
        if tok in ("sudo", "!"):
            continue
        return tok.split("/")[-1]
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B")
    ap.add_argument("--adapter", default="models/AINIX_NEO_terminal-lora")
    ap.add_argument("--eval", default="/tmp/nl2bash_test.csv")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--max-tokens", type=int, default=120)
    ap.add_argument("--out", default="docs/eval.json")
    args = ap.parse_args()

    from mlx_lm import load, generate

    seen = training_prompts()
    rows = load_eval(Path(args.eval), seen, args.limit)
    print(f"{len(rows)} held-out prompts (NL2Bash test, "
          f"{len(seen)} training prompts excluded)\n")

    report = {}
    for label, adapter in [("base", None), ("tuned", args.adapter)]:
        model, tok = load(args.model, adapter_path=adapter)
        outs = []
        for r in rows:
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": r["nl"]}]
            prompt = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                             enable_thinking=False)
            outs.append(generate(model, tok, prompt=prompt,
                                 max_tokens=args.max_tokens, verbose=False))

        parsed = [extract(o) for o in outs]
        cmds = [c or "false" for c, _ in parsed]
        ran = sandbox(cmds)
        from reward import score
        graded = [score(c, r["ref"]) for c, r in zip(cmds, rows)]

        n = len(rows)
        stats = {
            "answers": sum(c is not None and not REFUSAL.search(o)
                           for (c, _), o in zip(parsed, outs)),
            "contract": sum(u for _, u in parsed),
            "runs": sum(ran),
            "matches": sum(bool(c) and base_util(c) == base_util(r["ref"])
                           for (c, _), r in zip(parsed, rows)),
            "correct": sum(g["reward"] == 1.0 for g in graded),
            "plausible": sum(g["reward"] == 0.6 for g in graded),
            "n": n,
        }
        report[label] = {
            **stats,
            "samples": [{"nl": r["nl"], "ref": r["ref"], "got": c,
                         "contract": u, "ran": ok, "verdict": g["verdict"],
                         "why": g["why"]}
                        for r, (c, u), ok, g in
                        zip(rows, parsed, ran, graded)][:20],
        }
        print(f"  {label:6} answers {stats['answers']:2}/{n}  "
              f"contract {stats['contract']:2}/{n}  "
              f"runs {stats['runs']:2}/{n}  "
              f"same-utility {stats['matches']:2}/{n}  "
              f"CORRECT {stats['correct']:2}/{n}")

    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
