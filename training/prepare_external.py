#!/usr/bin/env python3
"""Merge external Linux/terminal datasets into the AINIX_NEO_terminal corpus.

Sources (HuggingFace, downloaded raw to dodge the datasets/py3.14 dill bug):
  - PocketDoc/Dans-Toolmaxx-ShellCommands   (bash terminal instructions)
  - iselabvn/Linux-terminal-tool-calling    (NL -> command tool calls)

Output: OpenAI messages JSONL, same shape generate.py writes, merged with any
repo-grounded records already in training/data/AINIX_NEO_terminal.jsonl.

    training/.venv/bin/python training/prepare_external.py \
        --out training/data/AINIX_NEO_terminal.jsonl --sample 400
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from huggingface_hub import hf_hub_download

SYSTEM = "You are the AINIX assistant."


def toolmaxx_records(limit: int) -> list[dict]:
    p = hf_hub_download("PocketDoc/Dans-Toolmaxx-ShellCommands",
                        "toolmaxx-bash-terminal.json", repo_type="dataset")
    data = json.load(open(p))
    out = []
    for row in data[:limit]:
        conv = {m["from"]: m["value"] for m in row["conversations"] if m["from"] != "system"}
        if "human" not in conv or "gpt" not in conv:
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": conv["human"]},
                {"role": "assistant", "content": conv["gpt"]},
            ],
            "meta": {"source": "hf:PocketDoc/Dans-Toolmaxx-ShellCommands",
                     "task": "terminal", "teacher": "human"},
        })
    return out


def toolcall_records(limit: int) -> list[dict]:
    p = hf_hub_download("iselabvn/Linux-terminal-tool-calling",
                        "linux_terminal_tool_calling_dataset.jsonl",
                        repo_type="dataset")
    out = []
    with open(p) as fh:
        for line in fh:
            if len(out) >= limit:
                break
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            msgs = row.get("messages", [])
            user = next((m["content"] for m in msgs if m["role"] == "user"), None)
            asst = next((m for m in msgs if m["role"] == "assistant"), None)
            if not user or not asst:
                continue
            # Collapse the exec tool call into plain assistant text.
            calls = asst.get("tool_calls") or []
            cmd = None
            for c in calls:
                fn = c.get("function", {})
                if fn.get("name") == "exec":
                    args = json.loads(fn.get("arguments", "{}"))
                    cmd = args.get("command")
            if not cmd:
                continue
            explain = (asst.get("content") or "").strip()
            body = json.dumps({"command": cmd, "explain": explain,
                               "mutates": True}, indent=2)
            out.append({
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": body},
                ],
                "meta": {"source": "hf:iselabvn/Linux-terminal-tool-calling",
                         "task": "terminal", "teacher": "human"},
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="training/data/AINIX_NEO_terminal.jsonl")
    ap.add_argument("--sample", type=int, default=400,
                    help="external records total (default 400)")
    args = ap.parse_args()

    half = args.sample // 2
    records = toolmaxx_records(half) + toolcall_records(args.sample - half)
    random.Random(7).shuffle(records)

    out = Path(args.out)
    existing = []
    if out.exists():
        for line in out.read_text().splitlines():
            try:
                rec = json.loads(line)
                if rec.get("meta", {}).get("teacher") == "human":
                    continue  # regenerate external slice, keep teacher slice
                existing.append(rec)
            except json.JSONDecodeError:
                continue

    tmp = out.with_suffix(".tmp")
    with tmp.open("w") as fh:
        for rec in existing + records:
            fh.write(json.dumps(rec) + "\n")
    tmp.rename(out)
    print(f"{len(existing)} grounded + {len(records)} external = "
          f"{len(existing) + len(records)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
