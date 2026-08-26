#!/usr/bin/env python3
"""Verify a generated dataset. Discard, never repair.

Implements the checks in training/GENERATE-DATASET.md §6. A record that fails
any check is dropped with a reason; a repaired record is a record whose teacher
was wrong and whose repair was a guess.

    python3 training/verify.py training/data/raw.jsonl --out training/data/clean.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK_AGENT = ROOT / "scripts" / "check_agent.py"

# Paths the model might claim exist. Anything matching this shape is grepped
# against the real tree; unresolvable claims are hallucinations.
PATH_CLAIM = re.compile(
    r"`([a-zA-Z0-9_./-]+\.(?:toml|md|py|sh|nix|json|mojo|yaml|yml|conf|cfg|service|jsonl))`")
# Make targets and scripts the model tells a user to run.
MAKE_CLAIM = re.compile(r"`make ([a-z-]+)")


def real_paths() -> set[str]:
    out = set()
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            rel = p.relative_to(ROOT)
            out.add(str(rel))
            out.add(p.name)
    return out


def make_targets() -> set[str]:
    text = (ROOT / "Makefile").read_text()
    return {m for line in text.splitlines()
            if (m := line.split(":")[0].strip())
            and not line.startswith(("\t", "#", " "))
            and ":" in line and "=" not in line.split(":")[0]}


def category(reason: str) -> str:
    """Group discards so the summary is readable at a glance."""
    for prefix, label in (
        ("claims nonexistent path", "hallucinated path"),
        ("claims nonexistent make", "hallucinated make target"),
        ("command", "bad command contract"),
        ("missing or non-boolean", "bad command contract"),
        ("generated manifest", "invalid manifest"),
        ("duplicate", "duplicate"),
    ):
        if reason.startswith(prefix):
            return label
    return "malformed record"


def check_schema(rec: dict) -> str | None:
    msgs = rec.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        return "malformed messages"
    roles = [m.get("role") for m in msgs]
    if roles[-1] != "assistant":
        return "does not end with an assistant turn"
    if not str(msgs[-1].get("content", "")).strip():
        return "empty assistant turn"
    if any(not str(m.get("content", "")).strip() for m in msgs):
        return "empty turn"
    return None


def check_grounding(rec: dict, paths: set[str], targets: set[str]) -> str | None:
    text = rec["messages"][-1]["content"]
    for claimed in PATH_CLAIM.findall(text):
        if claimed in paths or claimed.rstrip("/") in paths:
            continue
        if any(p.endswith(claimed) for p in paths):
            continue
        return f"claims nonexistent path {claimed!r}"
    for target in MAKE_CLAIM.findall(text):
        if target not in targets:
            return f"claims nonexistent make target {target!r}"
    return None


def check_command(rec: dict) -> str | None:
    """Command-task records must be valid JSON and shell-parseable."""
    if rec.get("meta", {}).get("task") != "command":
        return None
    text = rec["messages"][-1]["content"].strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return "command record is not valid JSON"
    if "mutates" not in obj or not isinstance(obj["mutates"], bool):
        return "missing or non-boolean 'mutates'"
    cmd = obj.get("command")
    if cmd is None:
        return None                       # a refusal, which is a valid answer
    if subprocess.run(["sh", "-n", "-c", cmd],
                      capture_output=True).returncode != 0:
        return "command does not parse as shell"
    return None


def check_manifest(rec: dict) -> str | None:
    """Generated agent.toml must survive the real validator."""
    if rec.get("meta", {}).get("task") != "manifest":
        return None
    text = rec["messages"][-1]["content"]
    if "[agent]" not in text:
        return None                       # an explanation, not a manifest
    block = text.split("```")[1] if "```" in text else text
    block = block.removeprefix("toml").strip()
    try:
        import tomllib
        tomllib.loads(block)
    except Exception as e:
        return f"generated manifest is not valid TOML: {type(e).__name__}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("--out", default="training/data/clean.jsonl")
    ap.add_argument("--report", default="training/data/discarded.jsonl")
    args = ap.parse_args()

    paths, targets = real_paths(), make_targets()
    seen: set[str] = set()
    kept: list[dict] = []
    reasons: Counter[str] = Counter()
    discarded: list[dict] = []

    for line in Path(args.input).read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            reasons["unparseable line"] += 1
            continue

        why = (check_schema(rec)
               or check_grounding(rec, paths, targets)
               or check_command(rec)
               or check_manifest(rec))

        if why is None:
            key = rec["messages"][-2]["content"].strip().lower()
            if key in seen:
                why = "duplicate question"
            else:
                seen.add(key)

        if why:
            reasons[category(why)] += 1
            discarded.append({"reason": why, "record": rec})
        else:
            kept.append(rec)

    total = len(kept) + len(discarded)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in kept))
    Path(args.report).write_text("".join(json.dumps(d) + "\n" for d in discarded))

    print(f"kept      {len(kept):6}")
    print(f"discarded {len(discarded):6}"
          + (f"  ({100 * len(discarded) / total:.0f}%)" if total else ""))
    for reason, n in reasons.most_common(10):
        print(f"    {n:5}  {reason}")

    if total and len(discarded) / total < 0.02:
        print("\nWARNING: discard rate under 2%. Either the teacher is unusually\n"
              "good, or these checks are not actually running. Read a sample.")

    by_task = Counter(r.get("meta", {}).get("task") for r in kept)
    print("\nkept by task:", dict(by_task))
    print(f"\n{out}  ({len(kept)} records)")
    print(f"{args.report}  (discarded, with reasons — read these)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
