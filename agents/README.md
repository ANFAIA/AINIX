# Agents

One process = one agent = one expert, with exactly the models and tools its
manifest grants and nothing else.

## Tiers

| Tier | Directory | May call | Model access |
|---|---|---|---|
| **user** | `agents/user/` | app agents | none — routes through app agents |
| **app** | `agents/app/` | app agents listed in `peers` | yes, per `models` |
| **system** | `agents/system/` | anything | yes |

A user agent cannot be called by an app agent. Only system agents may mutate the
registry or spawn other agents.

## Add an agent

```bash
scripts/new-agent.sh app my-agent
```

That copies `agents/_template/` into `agents/app/my-agent/`. Then:

1. Edit `agent.toml` — declare `models`, `tools`, `peers`, `quota`, `card`.
2. Write `main.mojo`.
3. `make agent-check NAME=app/my-agent` — validates the manifest against
   `agents/schema/agent.schema.json` and checks every grant resolves.
4. `make agent-run NAME=app/my-agent` — runs it against the local runner.

There is no central registry file to edit. `nix/agent.nix` discovers every
directory under `agents/{user,app,system}/` that contains an `agent.toml`.

## The rules that are enforced, not just documented

- A grant not in `agent.toml` **fails the build**, not the request.
- At runtime the agent gets its own uid, netns and cgroup; only granted sockets
  are mounted in. An ungranted model endpoint is unreachable, not merely denied.
- `agentd` verifies a capability token on every call and writes an audit record.

## Evolution

`[evolution]` in the manifest says who may change the agent: `self`, a named
`parent`, or `frozen`. Every accepted change is a new Nix derivation, so an
agent's history is a chain of content-addressed generations — see
[docs/EVOLUTION.md](../docs/EVOLUTION.md). Rollback is `nix profile rollback`,
not a rebuild.
