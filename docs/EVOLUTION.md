# Agent evolution

Agents change over time — a new tool appears, a model is swapped, a prompt is
sharpened. AINIX treats that as a first-class, *tracked* operation rather than an
edit someone made on a Tuesday.

## Why Nix is the tracker

Nix is content-addressed: an agent built from a manifest **is** a store path
derived from the hash of that manifest, its code, and its dependency closure.
So:

- Two agents with the same behaviour are the same store path. Identity is not a
  version string someone remembered to bump.
- An evolution step is a new derivation whose input closure contains the
  previous one. History is a DAG the build system already maintains.
- Rollback is `nix profile rollback` — the old closure was never mutated.
- "Which agents changed when X changed?" is `nix why-depends`, not archaeology.

Each accepted change appends one record to the agent's `lineage.json`:

```json
{
  "generation": 7,
  "parent": "sha256-…",           // previous store path
  "drv": "sha256-…",              // this store path
  "actor": "app/capability-planner",
  "mode": "parent",
  "changed": ["card.skills", "tools"],
  "reason": "filesearch gained glob support; expose it in the card",
  "reviewed_by": "human:ismael"    // or "auto"
}
```

The file is generated, never hand-edited. It is the audit trail.

## Who may evolve whom

`[evolution]` in `agent.toml`:

| `mode` | Meaning |
|---|---|
| `self` | The agent may propose changes to itself. Highest freedom; use for app agents whose domain shifts fast. |
| `parent` | Only the named `parent` agent may change it. |
| `frozen` | Only a human commit changes it. Default for system agents. |

`allow` lists the fields that may be rewritten. Two fields are **never**
allowed, for either mode: `tier` and `quota`. An agent cannot promote itself or
grant itself more resources — that is the whole point of the tiering.

The intended flow, and the reason `parent` exists: **user agents are evolved by
app agents.** When an app agent gains a capability, it rewrites the card and
surfaces of the user agents that front it, so the CLI or web UI exposes the new
feature without a human wiring it up. The user agent's own `allow` list bounds
how far that rewrite can go.

```toml
# agents/user/cli/agent.toml
[evolution]
mode   = "parent"
parent = "app/summarizer"
allow  = ["card", "prompt", "commands"]
review = "auto"
```

## The loop

1. An actor (the agent itself, or its parent) proposes a manifest diff to
   `agentd`.
2. `agentd` rejects anything outside `allow`, or any change to `tier`/`quota`.
3. The proposal is built: `nix build .#agents.<tier>-<name>`. An undeclared
   grant fails here, before anything runs.
4. `review = "required"` parks the new closure until a human approves;
   `review = "auto"` activates it directly.
5. Activation is a profile switch. The previous generation stays in the store,
   so a bad evolution is one rollback away.
6. `lineage.json` gets its record; `agentd` writes the audit entry.

## Guardrails worth stating plainly

Self-evolving agents are a real security surface. The design leans on limits
that hold even if an agent is fully compromised: it cannot change its own tier,
cannot raise its quota, cannot reach a socket that was never mounted, and cannot
activate a generation that failed to build. Everything softer than that —
prompt content, card text — is allowed to move freely, because it cannot widen
access.
