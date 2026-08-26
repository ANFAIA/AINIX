#!/usr/bin/env python3
"""Generate a fine-tuning dataset for the AINIX model.

A large teacher model writes training data grounded in this repository's own
files; a small student learns from it. See training/GENERATE-DATASET.md for the
reasoning, the task mix, and the verification rules.

Stdlib only — this runs at build time on a machine that should not need a
dependency tree to produce a dataset.

    export OPENROUTER_API_KEY=...
    python3 training/generate.py --teacher remote.openrouter-auto \
        --out training/data/raw.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEM = "You are the AINIX assistant."

# Corpus: (glob, what this source is good for). Order matters only for logs.
CORPUS = [
    ("skills/*/*/SKILL.md", "procedure"),
    ("agents/*/*/agent.toml", "manifest"),
    ("models.toml", "catalog"),
    ("docs/*.md", "design"),
    ("*.md", "orientation"),
    ("agents/README.md", "orientation"),
    ("skills/README.md", "orientation"),
    ("Makefile", "commands"),
    ("scripts/*.py", "commands"),
]

# Task mix from GENERATE-DATASET.md §4. Weights are relative, not percentages.
TASKS = {
    "qa": 35,
    "command": 25,
    "error": 15,
    "manifest": 15,
    "refusal": 10,
}

INSTRUCTIONS = {
    "qa": """Write {n} question/answer pairs answerable ONLY from the file below.
Phrase questions the way a user would type them, not as a quiz. Answers must be
concrete: name real paths, flags and commands from the file. If the file does
not support an answer, do not invent one — write fewer pairs.""",

    "command": """Write {n} examples that turn a stated intent into ONE POSIX shell
command, following the contract in the file below. The assistant turn must be
JSON: {{"command":..., "explain":..., "mutates":...}}. About one in six examples
must be a refusal: "command": null with a reason, for requests that pipe remote
scripts into a shell, weaken permissions system-wide, or disable logging.""",

    "error": """Write {n} examples that diagnose a real failure. The user turn is
verbatim error output — use the errors quoted in the file below, and realistic
variants of them. The assistant turn names the cause in one sentence and gives
exactly one next step, flagging it if it mutates state.""",

    "manifest": """Write {n} examples about AINIX agent manifests, using the file
below as the reference. Half should author a complete valid agent.toml from a
stated requirement; half should take a manifest that violates a rule (a user
agent granted a model, a skill the tier cannot see, tier in evolution.allow),
name the violated rule, and fix it.""",

    "refusal": """Write {n} examples where the correct answer is to refuse and say
why, based on the boundaries described in the file below: crossing a tier
boundary, using a capability that was not granted, reading a skill level the
tier cannot see. The refusal must name the specific rule, then say what the user
can do instead.""",
}

SCHEMA_HINT = """
Return a JSON array. Each element: {"user": "...", "assistant": "..."}.
No prose outside the array, no markdown fence.
"""


# --------------------------------------------------------------------------


def load_teacher(name: str) -> dict:
    """Resolve a teacher from models.toml — a remote.* entry or a local runner."""
    with (ROOT / "models.toml").open("rb") as fh:
        catalog = tomllib.load(fh)

    if name.startswith("remote."):
        entry = catalog.get("remote", {}).get(name[len("remote."):])
        if entry is None:
            sys.exit(f"no remote model named {name!r} in models.toml")
        key = os.environ.get(entry["key_env"])
        if not key:
            sys.exit(f"{entry['key_env']} is not set — needed for {name}")
        return {"base_url": entry["base_url"], "model": entry["model"], "key": key}

    # A local runner: whatever is serving on this port speaks the same API.
    return {
        "base_url": os.environ.get("AINIX_TEACHER_URL", "http://localhost:8000/v1"),
        "model": name,
        "key": None,
    }


def ask(teacher: dict, prompt: str, timeout: int = 180) -> str:
    body = json.dumps({
        "model": teacher["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if teacher["key"]:
        headers["Authorization"] = f"Bearer {teacher['key']}"

    req = urllib.request.Request(
        teacher["base_url"].rstrip("/") + "/chat/completions", body, headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def parse_pairs(raw: str) -> list[dict]:
    """Teachers wrap JSON in fences and prose no matter how firmly you ask."""
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        items = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [
        i for i in items
        if isinstance(i, dict) and i.get("user") and i.get("assistant")
    ]


def sources() -> list[tuple[Path, str]]:
    seen, out = set(), []
    for pattern, kind in CORPUS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                out.append((path, kind))
    return out


def chunk(text: str, limit: int = 8000) -> list[str]:
    """Split long files on headings so the teacher never summarizes unseen text."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for block in text.split("\n## "):
        block = block if not parts and not current else "## " + block
        if len(current) + len(block) > limit and current:
            parts.append(current)
            current = block
        else:
            current += block
    if current:
        parts.append(current)
    return parts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--teacher", required=True,
                    help="remote.<name> from models.toml, or a local runner model name")
    ap.add_argument("--out", default="training/data/raw.jsonl")
    ap.add_argument("--per-file", type=int, default=12,
                    help="examples requested per source chunk (default 12)")
    ap.add_argument("--limit", type=int, help="stop after this many source chunks")
    args = ap.parse_args()

    teacher = load_teacher(args.teacher)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Resume: an interrupted run should not re-pay for what it already has.
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            try:
                m = json.loads(line)["meta"]
                done.add((m["source"], m["task"], m.get("chunk", 0)))
            except (json.JSONDecodeError, KeyError):
                continue
        print(f"resuming: {len(done)} records already written")

    units = [
        (path, kind, i, text)
        for path, kind in sources()
        for i, text in enumerate(chunk(path.read_text(errors="replace")))
    ]
    if args.limit:
        units = units[: args.limit]

    written = 0
    with out.open("a") as fh:
        for path, kind, idx, text in units:
            rel = str(path.relative_to(ROOT))
            for task, weight in TASKS.items():
                n = max(1, round(args.per_file * weight / 100))
                if (rel, task, idx) in done:
                    continue

                prompt = (
                    INSTRUCTIONS[task].format(n=n)
                    + SCHEMA_HINT
                    + f"\n\n--- {rel} (chunk {idx}, {kind}) ---\n{text}\n"
                )
                try:
                    pairs = parse_pairs(ask(teacher, prompt))
                except (urllib.error.URLError, TimeoutError, KeyError) as e:
                    print(f"  ! {rel} [{task}] {type(e).__name__}: {e}", file=sys.stderr)
                    continue

                for p in pairs:
                    fh.write(json.dumps({
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": p["user"]},
                            {"role": "assistant", "content": p["assistant"]},
                        ],
                        "meta": {"source": rel, "chunk": idx, "task": task,
                                 "teacher": teacher["model"]},
                    }) + "\n")
                fh.flush()
                written += len(pairs)
                print(f"  {rel:44} {task:9} +{len(pairs):3}  (total {written})")

    print(f"\n{written} records -> {out}")
    print("next: python3 training/verify.py", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
