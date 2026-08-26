# recover

The machine is not working. Get it back to a shell a human can use.

`protected = true`: this file is changed by a human commit only. It is the
procedure that runs when the agents themselves are what broke, so no agent —
including a system agent — may rewrite it.

## Procedure

1. **A shell first.** Before diagnosing anything, confirm `/bin/sh` is reachable
   on tty1. If it is not, that is the only problem worth solving.
2. Identify what failed, in this order: agentd, then the model runners, then
   individual agents. A failure low in that list explains failures above it; the
   reverse is not true.
3. `journalctl -b -p err` for this boot. Read the *first* error, not the last —
   the last is usually a consequence.
4. If a bad agent generation is the cause, roll back rather than repair:
   `nix profile rollback`. The previous closure was never mutated and is known
   to have worked.
5. If a model runner is the cause, stop it. The machine is usable without
   inference; it is not usable without a shell.
6. Report what was done, what is still down, and what a human must decide.

## Never

Do not delete state, weights, or logs to make an error go away — the next
person needs them. Do not disable the audit log. Do not modify another skill as
part of a recovery; recovery is diagnosis and rollback, not redesign.
