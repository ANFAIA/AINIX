"""Normalise every record to one output shape, then merge the verified set.

The dataset teaches four competing shapes — 47% the {command, explain, mutates}
contract, 25% prose, 22% a bare command, 5% a `<reply>` wrapper. A model cannot
learn a contract from data that only uses it half the time, and which shape
wins on any given prompt is close to arbitrary.

This does not invent content. A bare command becomes a contract by wrapping it;
a `<reply>` wrapper is unwrapped and then wrapped properly; prose that answers
a question is left alone, because a Q&A record is not a command record and
forcing it into a command shape would be a lie. Records that claim to be
commands and are not usable as one are dropped.

`mutates` is inferred from the verb when the record does not say, erring toward
true: a false negative there means something irreversible runs without asking.

    training/.venv313/bin/python training/normalize.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Anything that writes, deletes, installs, sends, or changes configuration.
MUTATING = re.compile(
    r"\b(rm|mv|cp|touch|mkdir|rmdir|chmod|chown|chgrp|ln|dd|tee|truncate|"
    r"install|apt|apt-get|dnf|yum|pacman|pip|npm|make|git|kill|pkill|"
    r"systemctl|service|mount|umount|swapoff|swapon|useradd|usermod|userdel|"
    r"groupadd|passwd|crontab|iptables|sed -i|tar -c|zip|gzip|curl -O|wget|"
    r"scp|rsync|shutdown|reboot|mkfs|fdisk|parted)\b")

REDIRECT = re.compile(r"(?<![0-9])>{1,2}(?!&)")


def infer_mutates(cmd: str) -> bool:
    return bool(MUTATING.search(cmd) or REDIRECT.search(cmd))


def as_contract(answer: str) -> dict | None:
    """Turn whatever shape this record uses into the contract, or None if it
    is not a command record at all."""
    a = answer.strip()

    # Already the contract.
    if a.startswith("{"):
        try:
            d = json.loads(a)
            if isinstance(d.get("command"), str) and d["command"].strip():
                return {"command": d["command"].strip(),
                        "explain": str(d.get("explain") or d.get("explanation")
                                       or "").strip()[:300],
                        "mutates": bool(d.get("mutates",
                                              infer_mutates(d["command"])))}
        except json.JSONDecodeError:
            pass
        return None

    # A `<reply>`-wrapped command: unwrap, then wrap properly.
    m = re.match(r"<reply>\s*(.+?)\s*</reply>", a, re.DOTALL)
    if m:
        a = m.group(1).strip()

    # A bare command — one line, no prose punctuation at the end.
    if "\n" not in a and len(a) < 200 and not a.endswith((".", "?", "!", ":")):
        return {"command": a, "explain": "", "mutates": infer_mutates(a)}

    # A fenced command inside prose.
    m = re.search(r"```(?:[a-z]*\n)?(.+?)```", a, re.DOTALL)
    if m:
        cmd = m.group(1).strip().splitlines()[0].strip().removeprefix("$ ")
        if cmd:
            return {"command": cmd, "explain": "", "mutates": infer_mutates(cmd)}

    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", nargs="*", default=[
        "training/data/AINIX_NEO_terminal.jsonl",
        "training/data/distilled.jsonl"])
    ap.add_argument("--out", default="training/data/AINIX_NEO_v2.jsonl")
    args = ap.parse_args()

    stats = Counter()
    seen: dict[str, dict] = {}

    for path in args.inputs:
        p = ROOT / path
        if not p.exists():
            print(f"  ! missing: {path}")
            continue
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
                msgs = r["messages"]
                user, answer = msgs[1]["content"], msgs[-1]["content"]
            except (json.JSONDecodeError, KeyError, IndexError):
                stats["malformed"] += 1
                continue

            task = r.get("meta", {}).get("task", "")
            if task == "qa" or (len(answer) > 400 and "\n" in answer):
                # A question answered in prose is a legitimate record in its
                # own shape. Forcing it into a command contract would invent a
                # command the source never gave.
                stats["kept as prose"] += 1
                out = r
            else:
                c = as_contract(answer)
                if c is None:
                    stats["dropped"] += 1
                    continue
                stats["normalised"] += 1
                out = {**r, "messages": [msgs[0], msgs[1],
                                         {"role": "assistant",
                                          "content": json.dumps(c)}]}

            # Later inputs win: distilled records are verified, the older ones
            # are not.
            key = user.strip().lower()
            if key in seen:
                stats["deduped"] += 1
            seen[key] = out

    out = ROOT / args.out
    with out.open("w") as fh:
        for r in seen.values():
            fh.write(json.dumps(r) + "\n")

    print(f"{len(seen)} records -> {args.out}")
    for k, v in stats.most_common():
        print(f"  {v:5}  {k}")

    shapes = Counter()
    for r in seen.values():
        a = r["messages"][-1]["content"].strip()
        shapes["contract" if a.startswith('{"command"') else "prose"] += 1
    print("  shapes:", dict(shapes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
