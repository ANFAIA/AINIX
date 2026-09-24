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
3. `make agent-check AGENT=app/my-agent` — `scripts/check_agent.py` checks the
   manifest and that every grant resolves.
4. Run it against a local broker: start `agents/system/agentd/agentd.py`, then
   `python3 agents/lib/run_agent.py agents/app/my-agent` (or `mojo run
   main.mojo` from its directory).

There is no central registry file to edit. `nix/services/agents.nix` discovers
every directory under `agents/{user,app,system}/` that contains an
`agent.toml` and generates its unit and its uid.

## The rules that are enforced, not just documented

- An illegal grant **fails the build**: the Nix build of the image runs the
  same validator as CI.
- The agent registers by name; agentd reads its manifest from disk, and on the
  image binds the name to the agent's own uid via `SO_PEERCRED`.
- Each agent unit may open only Unix sockets, so it reaches models, peers,
  documents and tools only through agentd — which checks the grant on every
  request and writes an audit record with the reason.

See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for what is built and what
is still only designed.

## Evolution

`[evolution]` in the manifest says who may change the agent: `self`, a named
`parent`, or `frozen`. Every accepted change is a new Nix derivation, so an
agent's history is a chain of content-addressed generations — see
[docs/EVOLUTION.md](../docs/EVOLUTION.md). Rollback is `nix profile rollback`,
not a rebuild.
