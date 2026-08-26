# validate-model

## Procedure

1. **Evaluate on held-out data only.** The model trained on all of
   `training/data/`, so nothing in there can measure it. Use the NL2Bash test
   split (`dilkushsingh/NL2Bash`, MIT) — a source never used in training — and
   exclude any prompt that overlaps the training data anyway.
2. Always run **base and tuned in the same invocation**, same sampler, same
   prompts. A number without its baseline is not a result.
   ```
   training/.venv313/bin/python training/evaluate.py --limit 60
   ```
3. **Report effect-equivalence as the headline.** `training/reward.py` runs
   the candidate and the reference in identical seeded containers and compares
   stdout and the filesystem. That is the only column that means "right".

## What the weaker columns are worth

| column | what it hides |
|---|---|
| `answers` | says nothing about correctness — a confident wrong command counts |
| `contract` | format, which the system prompt controls, not the weights |
| `runs` | under-counts (`touch /testbed/x` is right and fails on a sandbox with no `/testbed`) and over-credits (`ls \| sort -r` runs fine and answers the wrong question) |
| `same utility` | counts `cp -r` as `cp` |

The gap between them is large enough to mislead: one run read 39/60 on
same-utility and 22/60 on effect-equivalence. Quote the strict number.

## Say what the number is not

State the sample size and that `same utility` is a proxy. With n=60, a jump
from 5 to 22 is z≈5.4 and real; a jump from 22 to 25 is not a result.
