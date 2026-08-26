#!/usr/bin/env python3
"""Download and convert every external Linux/terminal dataset needed for
AINIX_NEO_terminal, then merge everything into one deduplicated JSONL.

Sources (HuggingFace, raw files — the datasets lib is broken on py3.14):
  PocketDoc/Dans-Toolmaxx-ShellCommands      bash + macos terminal instructions
  iselabvn/Linux-terminal-tool-calling       NL -> exec tool calls
  darkknight25/Linux_Terminal_Commands_Dataset  command/category/description
  KonradSzafer/stackoverflow_linux           SO linux Q&A

Kaggle needs ~/.kaggle/kaggle.json which is not present on this machine —
add it and re-run to include Kaggle mirrors of the same corpora.

Output layout:
  training/data/sources/<name>.jsonl    one converted source each
  training/data/AINIX_NEO_terminal.jsonl merged, deduped, ready for train.py

    training/.venv/bin/python training/download_datasets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "training/data/raw"
SRC = ROOT / "training/data/sources"
FINAL = ROOT / "training/data/AINIX_NEO_terminal.jsonl"

SYSTEM = "You are the AINIX assistant."


def record(user: str, assistant: str, source: str, task: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": assistant.strip()},
        ],
        "meta": {"source": source, "task": task, "teacher": "human"},
    }


def contract(cmd: str, explain: str, mutates: bool = True) -> str:
    return json.dumps({"command": cmd, "explain": explain,
                       "mutates": mutates}, indent=2)


def write(name: str, records: list[dict]) -> Path:
    SRC.mkdir(parents=True, exist_ok=True)
    out = SRC / f"{name}.jsonl"
    seen, rows = set(), []
    for r in records:
        key = (r["messages"][1]["content"].lower(),
               r["messages"][2]["content"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)
    with out.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"{name:28} {len(rows):5} records -> {out.name}")
    return out


# --------------------------------------------------------------------------
# Converters
# --------------------------------------------------------------------------


def conv_toolmaxx() -> None:
    """ShareGPT-style {from,value} terminal instructions."""
    for flavor, fname in [("bash", "toolmaxx-bash-terminal.json"),
                          ("macos", "toolmaxx-MacOS-shell-terminal.json")]:
        p = hf_hub_download("PocketDoc/Dans-Toolmaxx-ShellCommands", fname,
                            repo_type="dataset")
        recs = []
        for row in json.load(open(p)):
            m = {x["from"]: x["value"] for x in row["conversations"]
                 if x["from"] != "system"}
            if "human" not in m or "gpt" not in m:
                continue
            recs.append(record(m["human"], m["gpt"],
                               f"hf:toolmaxx-{flavor}", "terminal"))
        write(f"toolmaxx-{flavor}", recs)


def conv_toolcalling() -> None:
    """exec tool calls -> plain {command,explain,mutates} contract."""
    p = hf_hub_download("iselabvn/Linux-terminal-tool-calling",
                        "linux_terminal_tool_calling_dataset.jsonl",
                        repo_type="dataset")
    recs = []
    for line in open(p):
        try:
            msgs = json.loads(line).get("messages", [])
        except json.JSONDecodeError:
            continue
        user = next((m["content"] for m in msgs if m["role"] == "user"), None)
        asst = next((m for m in msgs if m["role"] == "assistant"), None)
        if not user or not asst:
            continue
        cmd = None
        for c in asst.get("tool_calls") or []:
            fn = c.get("function", {})
            if fn.get("name") == "exec":
                try:
                    cmd = json.loads(fn.get("arguments", "{}")).get("command")
                except json.JSONDecodeError:
                    pass
        if not cmd:
            continue
        explain = (asst.get("reasoning_content") or "").strip()
        # First sentence only — keep answers short.
        explain = explain.split(". ")[0][:200]
        recs.append(record(user, contract(cmd, explain),
                           "hf:iselabvn-terminal-tool-calling", "command"))
    write("terminal-tool-calling", recs)


def conv_darkknight() -> None:
    """{command, category, description} rows -> intent/command pairs."""
    p = hf_hub_download("darkknight25/Linux_Terminal_Commands_Dataset",
                        "LINUX_TERMINAL_COMMANDS.jsonl", repo_type="dataset")
    recs = []
    for line in open(p):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cmd, desc, cat = row.get("command"), row.get("description"), \
            row.get("category")
        if not (cmd and desc):
            continue
        user = f"How do I do this in the terminal ({cat.lower() if cat else 'linux'})? {desc}"
        out = row.get("example_output") or ""
        explain = desc + (f" Example output: {out}" if out and out !=
                          "[No output, changes directory]" else "")
        recs.append(record(user, contract(cmd, explain),
                           "hf:linux-terminal-commands", "command"))
    write("linux-terminal-commands", recs)


def conv_stackoverflow() -> None:
    """SO linux Q&A -> qa pairs (answers can be long; trim hard)."""
    recs = []
    for split in ["train", "test"]:
        info = {
            "train": "data/train-00000-of-00001-d51f3f896df1e48d.parquet",
            "test": "data/test-00000-of-00001-7677d6b23d7696f9.parquet",
        }[split]
        p = hf_hub_download("KonradSzafer/stackoverflow_linux", info,
                            repo_type="dataset")
        for row in pq.read_table(p).to_pylist():
            q = (row.get("question") or "").strip()
            a = (row.get("answer") or "").strip()
            title = (row.get("title") or "").replace("linux - ", "")
            if not q or not a:
                continue
            if len(a) > 1500:
                a = a[:1500].rsplit("\n", 1)[0] + "\n[...]"
            recs.append(record(f"{title}\n\n{q}", a,
                               f"hf:stackoverflow-linux/{split}", "qa"))
    write("stackoverflow-linux", recs)


CONVERTERS = [conv_toolmaxx, conv_toolcalling, conv_darkknight,
              conv_stackoverflow]


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------


def merge() -> int:
    parts: dict[tuple[str, str], dict] = {}

    def add(rec: dict) -> None:
        key = (rec["messages"][1]["content"].lower().strip(),
               rec["messages"][2]["content"].strip())
        # Teacher/synth records win over human data on collision: they are
        # grounded in this repo or Docker-verified.
        rank = 0 if rec.get("meta", {}).get("teacher") == "human" else 1
        old = parts.get(key)
        if old is None or (rank == 1 and
                           old.get("meta", {}).get("teacher") == "human"):
            parts[key] = rec

    # Existing final file: keep grounded (teacher) + synth records.
    if FINAL.exists():
        for line in FINAL.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("meta", {}).get("teacher") != "human":
                add(rec)

    for src in sorted(SRC.glob("*.jsonl")):
        for line in src.read_text().splitlines():
            try:
                add(json.loads(line))
            except json.JSONDecodeError:
                continue

    rows = sorted(parts.values(),
                  key=lambda r: r.get("meta", {}).get("source", ""))
    tmp = FINAL.with_suffix(".tmp")
    with tmp.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    tmp.rename(FINAL)

    by_task: dict[str, int] = {}
    for r in rows:
        by_task[r.get("meta", {}).get("task", "?")] = \
            by_task.get(r.get("meta", {}).get("task", "?"), 0) + 1
    print(f"\nmerged {len(rows)} unique records -> {FINAL.name}")
    print("by task:", dict(sorted(by_task.items(), key=lambda x: -x[1])))
    return len(rows)


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    failed = []
    for conv in CONVERTERS:
        name = conv.__name__
        try:
            conv()
        except Exception as e:
            print(f"{name}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
            failed.append(name)
    n = merge()
    if failed:
        print(f"\nwarning: {len(failed)} converters failed: {failed}",
              file=sys.stderr)
    if n < 1000:
        print("\nwarning: dataset small — consider running "
              "synthesize_docker.py to grow the verified slice",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
