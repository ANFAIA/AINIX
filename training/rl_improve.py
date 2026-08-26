#!/usr/bin/env python3
"""RL-style dataset testing + improvement loop (RAFT / rejection sampling).

The current policy (Qwen3.5-0.8B base) rolls out K answers per task prompt;
the Docker sandbox scores every answer that claims a command (reward=1 iff it
parses and exits 0). The loop then:

  TESTS    per-prompt pass rate = how well the data's own distribution is
           learned zero-shot by the base model. Low pass rates mark weak spots
           of the dataset (ambiguous intents, unanswerable phrasings).
  IMPROVES every passing rollout is kept as a new verified SFT record
           (meta.rl.reward=1) — hard positives mined from the model itself.
           Prompts with zero passing rollouts are written to the report with
           their reference answer for targeted teacher regeneration.

This is the reward-model-free half of RL: environment-gated rejection
sampling. Swap the sampler for GRPOTrainer + docker_reward as the reward
function when a CUDA box is available.

Needs: Docker daemon, training/.venv (torch+transformers), the datasets
already merged into training/data/AINIX_NEO_terminal.jsonl.

    training/.venv/bin/python training/rl_improve.py --prompts 20 --rollouts 4
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthesize_docker import (docker_reward, start_sandbox, stop_sandbox)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "training/data/AINIX_NEO_terminal.jsonl"
OUT = ROOT / "training/data/rl_augmented.jsonl"
REPORT = ROOT / "training/data/rl_report.json"


def extract_contract(text: str) -> dict | None:
    """Pull {"command":...} out of prose/fenced model output."""
    m = re.search(r"\{[^{}]*\"command\"[^{}]*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        c = json.loads(m.group(0))
        return c if isinstance(c.get("command"), str) else None
    except json.JSONDecodeError:
        return None


# Tools the debian sandbox will never have — a record using them is not
# broken, it is another distro's answer.
FOREIGN_DISTRO = ("dnf", "yum ", "yum", "pacman -", "zypper", "apk add",
                  "brew ", "apt-get", "apt ")

# Commands whose success depends on runtime state the sandbox cannot seed
# (an existing pid, an existing service, a populated journal). A nonzero exit
# here is inconclusive, not a dataset bug.
STATE_DEPENDENT = ("kill ", "pkill", "systemctl ", "journalctl", "service ",
                   "apparmor_parser", "aa-", "umount", "swapoff")


def verify_reference(sandbox: str, cmd: str) -> str:
    """Three-way verdict for a dataset record's own answer."""
    if any(cmd.lstrip().startswith(t) or f"| {t}" in cmd for t in FOREIGN_DISTRO):
        return "skip-foreign-distro"
    r = docker_reward(sandbox, cmd)
    if r["reward"] == 1:
        return "ok"
    if r.get("exit_code") == 127 or "syntax" in r.get("reason", "") \
            or r.get("reason", "").startswith("hard-refuse"):
        return "bad"
    if any(cmd.lstrip().startswith(t) for t in STATE_DEPENDENT):
        return "skip-state"
    return "unverified"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--prompts", type=int, default=30)
    ap.add_argument("--rollouts", type=int, default=4)
    ap.add_argument("--max-new", type=int, default=140)
    ap.add_argument("--base", default="Qwen/Qwen3.5-0.8B")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    rng = random.Random(args.seed)

    pool = []
    seen_prompts = set()
    for line in DATA.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = r.get("messages", [])
        if len(m) < 3:
            continue
        task = r.get("meta", {}).get("task", "")
        if task not in ("command", "terminal"):
            continue
        u = m[1]["content"]
        if u.lower() in seen_prompts:
            continue
        seen_prompts.add(u.lower())
        pool.append({"user": u,
                     "ref": r["messages"][2]["content"],
                     "src": r.get("meta", {}).get("source", "")})
    rng.shuffle(pool)
    tasks = pool[: args.prompts]
    print(f"{len(tasks)} eval prompts x {args.rollouts} rollouts")

    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, dtype=torch.bfloat16).to("mps")
    model.eval()

    sandbox = start_sandbox()
    import atexit
    atexit.register(stop_sandbox, sandbox)

    results = []
    kept = weak = pruned = 0
    pruned_keys: set[str] = set()
    t_start = time.time()
    with OUT.open("w") as fh:
        for i, task in enumerate(tasks):
            msgs = [{"role": "system",
                     "content": ("You are the AINIX assistant. Answer with ONLY "
                                 "a JSON object: {\"command\":..., "
                                 "\"explain\":..., \"mutates\":true|false}.")},
                    {"role": "user", "content": task["user"]}]
            enc = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                          return_tensors="pt",
                                          return_dict=True).to("mps")
            rewards, best = [], None
            for _ in range(args.rollouts):
                with torch.no_grad():
                    out = model.generate(**enc, max_new_tokens=args.max_new,
                                         do_sample=True, temperature=1.0,
                                         top_p=0.95,
                                         pad_token_id=tok.eos_token_id)
                text = tok.decode(out[0][enc["input_ids"].shape[1]:],
                                  skip_special_tokens=True)
                c = extract_contract(text)
                if c is None:
                    rewards.append(0)
                    continue
                r = docker_reward(sandbox, c["command"])
                rewards.append(r["reward"])
                if r["reward"] == 1 and best is None:
                    best = json.dumps(c, indent=2)

            # Dataset self-test: does the record's own reference answer
            # survive the same environment? Only provable bugs (command not
            # found, syntax error, hard-refuse pattern) prune a record.
            ref_cmd = extract_contract(task["ref"])
            ref_verdict = "no-command"
            if ref_cmd is not None:
                ref_verdict = verify_reference(sandbox, ref_cmd["command"])

            pass_rate = sum(rewards) / len(rewards)
            entry = {"user": task["user"], "source": task["src"],
                     "pass_rate": pass_rate,
                     "reference_verdict": ref_verdict}
            if ref_verdict == "bad":
                pruned += 1
                entry["verdict"] = "dataset-bad-pruned"
                entry["reference"] = task["ref"]
            elif pass_rate == 1.0:
                entry["verdict"] = "learned"
            elif best is not None:
                # Keep a verified hard positive as new training data.
                fh.write(json.dumps({
                    "messages": [
                        {"role": "system",
                         "content": "You are the AINIX assistant."},
                        {"role": "user", "content": task["user"]},
                        {"role": "assistant", "content": best},
                    ],
                    "meta": {"source": f"rl:{task['src']}", "task": "command",
                             "teacher": f"raft:{args.base}",
                             "verified": True, "reward": 1,
                             "rl": {"pass_rate": pass_rate}},
                }) + "\n")
                fh.flush()
                kept += 1
                entry["verdict"] = "hard-positive-kept"
            else:
                weak += 1
                entry["verdict"] = "model-weak-ref-ok"
                entry["reference"] = task["ref"]
                if ref_verdict == "ok":
                    # Environment-approved reference becomes a verified record
                    # replacing whatever the model could not learn.
                    fh.write(json.dumps({
                        "messages": [
                            {"role": "system",
                             "content": "You are the AINIX assistant."},
                            {"role": "user", "content": task["user"]},
                            {"role": "assistant",
                             "content": json.dumps(ref_cmd, indent=2)},
                        ],
                        "meta": {"source": f"rl:{task['src']}",
                                 "task": "command",
                                 "teacher": f"raft:{args.base}",
                                 "verified": True, "reward": 1,
                                 "rl": {"pass_rate": pass_rate}},
                    }) + "\n")
                    kept += 1
                    entry["verdict"] = "hard-positive-kept"
            results.append(entry)
            if entry["verdict"] == "dataset-bad-pruned":
                pruned_keys.add(task["user"].lower())
            bar = "#" * round(pass_rate * 10)
            print(f"[{i + 1:3}/{len(tasks)}] {bar:<10} "
                  f"{pass_rate:.0%} {entry['verdict']:18} "
                  f"{task['user'][:55]}")

    n_learned = sum(1 for r in results if r["verdict"] == "learned")
    avg = sum(r["pass_rate"] for r in results) / max(1, len(results))
    report = {
        "policy": args.base,
        "prompts": len(results),
        "rollouts_per_prompt": args.rollouts,
        "mean_pass_rate": round(avg, 3),
        "fully_learned": n_learned,
        "hard_positives_kept": kept,
        "dataset_bugs_pruned": pruned,
        "weak_spots": weak,
        "minutes": round((time.time() - t_start) / 60, 1),
        "results": sorted(results, key=lambda r: r["pass_rate"]),
    }
    REPORT.write_text(json.dumps(report, indent=2))
    print(f"\nmean pass rate {avg:.0%} | learned {n_learned} | "
          f"kept {kept} new verified records -> {OUT.name}")
    print(f"pruned {pruned} broken records | weak spots {weak} -> {REPORT.name}")

    # Merge: drop environment-failing records, add RL-mined hard positives.
    existing = {}
    for line in DATA.read_text().splitlines():
        try:
            r = json.loads(line)
            key = r["messages"][1]["content"].lower()
            if key in pruned_keys:
                continue
            existing[key] = r
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    added = updated = 0
    if OUT.exists() and kept:
        for line in OUT.read_text().splitlines():
            r = json.loads(line)
            key = r["messages"][1]["content"].lower()
            if key in existing:
                # Same intent, now environment-verified: adopt the verified
                # answer and stamp the reward.
                old = existing[key]
                old["messages"][2] = r["messages"][2]
                old["meta"]["verified"] = True
                old["meta"]["reward"] = 1
                old["meta"]["rl"] = r["meta"].get("rl")
                updated += 1
            else:
                existing[key] = r
                added += 1
    tmp = DATA.with_suffix(".tmp")
    rows = sorted(existing.values(),
                  key=lambda r: r.get("meta", {}).get("source", ""))
    with tmp.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    tmp.rename(DATA)
    print(f"merged +{added} new, {updated} verified-in-place, "
          f"-{len(pruned_keys)} pruned -> {DATA.name} (now {len(rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
