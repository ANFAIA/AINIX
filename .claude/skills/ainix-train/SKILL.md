---
name: ainix-train
description: Fine-tune or evaluate the AINIX model. Use when asked to train, fine-tune, distill a dataset, or measure whether a model improved. Carries the failures already paid for once.
---

Read `skills/system/train-model` and `skills/system/validate-model` first —
they are the authority, this is the entry point.

**Before training**

- Use `training/.venv313`. The 3.14 venv cannot pickle and `datasets.map` dies
  before training starts.
- Free the GPU: `make stop`, kill agents, remove stray sandbox containers. A
  run OOM'd on Metal at step 344 because the runner was still holding memory.
- Size `--max-seq` to the data, not to a round number. Measure the record
  length distribution first.

**Training**

```bash
training/.venv313/bin/python training/train.py --epochs 2 --max-seq 512 \
  --data training/data/AINIX_NEO_terminal.jsonl --out models/<name>
```

**Validation — held out, always**

```bash
training/.venv313/bin/python training/evaluate.py --limit 60
```

Runs base and tuned in one invocation on NL2Bash test, a source never used in
training. Report the `CORRECT` column — effect-equivalence, measured by running
candidate and reference in identical containers. `runs` and `same-utility`
flatter both models and must not be quoted as accuracy.

**Never**

- Never measure on `training/data/` — the model trained on all of it.
- Never copy a GGUF into the weights cache without loading it first. A failed
  export left one that loads silently and emits token soup.
- Never back up nothing: `training/data/` is gitignored.
