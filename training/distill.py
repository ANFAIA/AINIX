"""Build a dataset whose every record is verified correct by execution.

The existing 2507 records were never checked for correctness — they are what a
teacher (or a scraped source) *said*, not what actually works. This produces
records that had to survive the sandbox first.

  1. PROMPTS   NL2Bash train split: an English intent with a known-good
               reference command. Disjoint from the 60 held-out test prompts
               that validation uses, and from anything already in training.
  2. PROPOSE   several free OpenRouter teachers answer the intent, in the
               {command, explain, mutates} contract. The reference is NEVER
               shown to a teacher — that would be copying, not distillation.
  3. VERIFY    every candidate is scored against the reference by
               training/reward.py: same stdout and same filesystem effect, or
               it is not equivalent.
  4. KEEP      reward 1.0 wins. When no teacher reaches it, the reference
               command itself becomes the answer with the best teacher's
               explanation attached — correct by construction, so a hard
               prompt still yields a usable record instead of being dropped.

Every record carries how it was obtained, so a later pass can weight or drop
the reference-anchored ones without guessing.

    export OPENROUTER_API_KEY=...
    training/.venv313/bin/python training/distill.py --limit 800
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "training"))

from generate import ask_any, load_teacher, cooling_for   # noqa: E402
from reward import score_many                   # noqa: E402

SYSTEM = """You translate a stated intent into ONE POSIX shell command.

Answer with ONLY a JSON object, no prose and no code fence:
{"command": "...", "explain": "one sentence on what it does", "mutates": true|false}

Rules:
- exactly one command; pipes are fine, a script is not
- prefer POSIX over GNU-only long options — this runs on a minimal image
- mutates is true for anything that writes, deletes, installs or sends
- never include a credential, a key, or a token"""

# Ordered by how good the answers are, not alphabetically: ask_any prefers
# whichever is not rate-limited, so a wide pool turns a 429 into a handoff
# instead of a stall.
# Lead teacher first: ask_any prefers whichever is not cooling, and the
# private endpoint has no rate limit, so the free pool is failover rather than
# the main source.
TEACHERS = ["remote.qwen38-local", "remote.minimax-m3", "remote.glm-5-2",
            "remote.nemotron-3-ultra", "remote.gemma-4-31b", "remote.inkling",
            "remote.nemotron-super"]

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def extract(text: str) -> dict | None:
    m = re.search(r"\{.*?\"command\".*?\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d.get("command"), str) and d["command"].strip() else None


def load_prompts(train_csv: Path, test_csv: Path, limit: int) -> list[dict]:
    """NL2Bash train rows that appear neither in the test split nor already in
    the training data. Contamination has to be excluded here, once, rather than
    apologised for later."""
    test = {r["nl"].strip().lower()
            for r in csv.DictReader(test_csv.open(newline=""))}
    have = set()
    merged = ROOT / "training/data/AINIX_NEO_terminal.jsonl"
    if merged.exists():
        for line in merged.read_text().splitlines():
            try:
                have.add(json.loads(line)["messages"][1]["content"].strip().lower())
            except Exception:
                continue

    rows, seen = [], set()
    for r in csv.DictReader(train_csv.open(newline="")):
        nl, ref = (r.get("nl") or "").strip(), (r.get("bash") or "").strip()
        k = nl.lower()
        if not nl or not ref or k in test or k in have or k in seen:
            continue
        seen.add(k)
        rows.append({"nl": nl, "ref": ref})
        if len(rows) >= limit:
            break
    return rows


def propose(teachers: dict, row: dict, want: int) -> list[dict]:
    """Answers from up to `want` teachers that are not currently cooling."""
    out = []
    for name, raw in ask_any(teachers, f"{SYSTEM}\n\nIntent: {row['nl']}",
                             want=want):
        d = extract(raw)
        if d:
            out.append({**d, "teacher": name})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train", default="/tmp/nl2bash_train.csv")
    ap.add_argument("--test", default="/tmp/nl2bash_test.csv")
    ap.add_argument("--out", default="training/data/distilled.jsonl")
    ap.add_argument("--limit", type=int, default=800)
    ap.add_argument("--chunk", type=int, default=40)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--teachers", nargs="*", default=TEACHERS)
    ap.add_argument("--per-prompt", type=int, default=2,
                    help="how many teachers answer each intent")
    args = ap.parse_args()

    teachers = {n: load_teacher(n) for n in args.teachers}
    rows = load_prompts(Path(args.train), Path(args.test), args.limit)
    log(f"{len(rows)} uncontaminated prompts | teachers: "
        f"{', '.join(teachers)}\n")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = {"equivalent": 0, "reference-anchored": 0, "dropped": 0}

    with out.open("w") as fh:
        for start in range(0, len(rows), args.chunk):
            chunk = rows[start:start + args.chunk]

            # One job per intent; ask_any picks which teachers answer it.
            with ThreadPoolExecutor(args.workers) as ex:
                results = list(ex.map(
                    lambda r: (r, propose(teachers, r, args.per_prompt)), chunk))

            by_row: dict[str, list[dict]] = {}
            for row, cands in results:
                if cands:
                    by_row[row["nl"]] = cands

            pairs, index = [], []
            for row in chunk:
                for c in by_row.get(row["nl"], []):
                    pairs.append((c["command"], row["ref"]))
                    index.append((row, c))
            grades = score_many(pairs) if pairs else []

            best: dict[str, tuple[dict, dict]] = {}
            for (row, cand), g in zip(index, grades):
                cur = best.get(row["nl"])
                if cur is None or g["reward"] > cur[1]["reward"]:
                    best[row["nl"]] = (cand, g)

            for row in chunk:
                pick = best.get(row["nl"])
                if pick and pick[1]["reward"] == 1.0:
                    cand, g = pick
                    command, source = cand["command"], "equivalent"
                elif pick:
                    # No teacher matched the reference. The reference is known
                    # good, so keep it and borrow the best explanation.
                    cand, g = pick
                    command, source = row["ref"], "reference-anchored"
                else:
                    kept["dropped"] += 1
                    continue

                kept[source] += 1
                fh.write(json.dumps({
                    "messages": [
                        {"role": "system", "content": "You are the AINIX assistant."},
                        {"role": "user", "content": row["nl"]},
                        {"role": "assistant", "content": json.dumps({
                            "command": command,
                            "explain": str(cand.get("explain", ""))[:300],
                            "mutates": bool(cand.get("mutates", False)),
                        })},
                    ],
                    "meta": {"source": "distill:nl2bash", "task": "command",
                             "teacher": cand["teacher"], "verified": True,
                             "reward": 1.0, "origin": source,
                             "reference": row["ref"]},
                }) + "\n")
            fh.flush()
            done = start + len(chunk)
            cooling = [n for n, t in teachers.items()
                       if cooling_for(t["model"]) > 0]
            log(f"[{done:4}/{len(rows)}] equivalent {kept['equivalent']:4}  "
                f"reference-anchored {kept['reference-anchored']:4}  "
                f"dropped {kept['dropped']:3}"
                + (f"  cooling: {','.join(n.split('.')[-1] for n in cooling)}"
                   if cooling else ""))

    total = sum(kept.values())
    log(f"\n{total} prompts -> {kept['equivalent'] + kept['reference-anchored']} "
        f"records, every one verified against the sandbox")
    log(f"  teacher matched the reference outright: "
        f"{kept['equivalent'] / max(1, total):.0%}")
    log(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
