# explain-error

A command failed. Explain why, and what to do next.

## Procedure

1. Read the **last** error line first. It is usually the real failure; the lines
   above it are context, and the lines below are cleanup noise.
2. Classify it before explaining:
   - *not found* — a missing binary, path, or package
   - *permission* — wrong user, wrong mode, read-only mount
   - *usage* — the command ran but the arguments were wrong
   - *runtime* — the command was right and the work failed
3. Say what happened in one sentence, in the user's words, not the tool's.
4. Give exactly one next step. If several would work, pick the safest reversible
   one and mention the others only if asked.
5. If the fix mutates state — installs, deletes, writes, sends — say so
   explicitly and let the user run it. Never present a mutating command as if
   it were a diagnostic.

## When not to guess

If the error text does not actually say what failed, say that. "This error does
not say which file it could not open; run it with `-v`" is a better answer than
a confident wrong cause.
