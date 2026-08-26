# agentd

The only process that knows where anything is.

Agents hold manifests. agentd holds addresses — the model endpoint, every
peer's queue, every skill's path — and hands out nothing a manifest did not
ask for. That is what makes a manifest enforceable rather than advisory: an
agent with no grant for `gemma-3-1b` cannot reach the runner, because it never
learns the URL.

## What it enforces

| rule | effect |
|---|---|
| model grants | `infer` is refused unless the model is in the caller's `models` |
| peer lists | `task` is refused unless the callee is in the caller's `peers` |
| tier direction | user → app only; app → app; system → anything |
| skill levels | a tier reads its own level and everything above it, never below |

Deny is the default, every decision is audited with a reason, and a refusal is
an answer — the base library raises `Denied`, which agents do not retry.

## Protocol

Newline-delimited JSON over a Unix socket (`$AINIX_SOCK`, default
`/run/ainix/agentd.sock`). Small and greppable on purpose: an audit trail
nobody can read with `socat` is not one.

```
{"op":"register","manifest":{...}}        -> {"ok":true,"name":"app/shell-expert"}
{"op":"discover","skill":"shell.ask"}     -> {"ok":true,"cards":[...]}
{"op":"task","to":"app/shell-expert",...} -> {"ok":true,"output":...}
{"op":"infer","model":"gemma-3-1b",...}   -> {"ok":true,"content":"..."}
{"op":"skill","name":"shell-command"}     -> {"ok":true,"text":"..."}
{"op":"status"}                           -> registry + last 20 audit lines
```

Identity is per-connection and set by `register`; an agent cannot claim to be
another by asking nicely.

## Frozen

`evolution.mode = "frozen"`. The thing that enforces the rules does not get to
rewrite itself, and it holds no model grant — brokering inference is not the
same as being allowed to use it.
