# AINIX architecture

What is built, how each rule is enforced, and — separately, at the end — what
is designed but not built yet. The two used to be mixed in this file; a reader
could not tell a plan from a property.

## The two planes

**Model plane** — a small number of shared model runners, each an
OpenAI-compatible endpoint. Locally that is llama.cpp in a 96 MB distroless
container (`runtime/Dockerfile.llamacpp`); on the image it is llama.cpp as a
hardened systemd service (`nix/services/runner.nix`). MAX is the intended
runtime for GPU hardware and does not run a model on macOS — see
[FINDINGS.md](FINDINGS.md).

**Agent plane** — many agents, each a process with its own uid and cgroup.
Agents hold *grants* to models by name; they never load weights and never
learn the runner's address.

Keeping these apart is not tidiness. N agents each loading a 1B model is N × the
memory, and on a GPU N × the VRAM. One runner, many agents, brokered access.

```
  user/shell (console, run by a human)
       │  task
       ▼
    agentd ──── registry · identity · grants · clearance · audit
       │                                   │
       │  task                             │  infer (only agentd holds the URL)
       ▼                                   ▼
  app/shell-expert                    model runner (llama.cpp, :8000)
```

## Identity — who is calling

An agent registers with a **name only**. agentd reads that agent's manifest
from the agent tree on disk; a caller that sends a manifest is refused. Every
grant that applies is the one Nix built and a human reviewed, never one the
caller wrote.

On the image, agentd runs with `AINIX_IDENTITY=uid`: each agent runs as system
user `ainix-<tier>-<name>` (generated from the tree by `nix/services/agents.nix`)
and agentd accepts a name only from that uid, read from the kernel with
`SO_PEERCRED`. A process that can open the broker's socket still cannot act as
an agent whose uid it does not have. In development the mode is `name`, and
every registration's audit line says `UNBOUND`.

## Enforcement — where each rule lives

| Layer | When | What it refuses |
|---|---|---|
| `scripts/check_agent.py` | in CI, and **as a step of the Nix build** | an undeclared model, a peer that does not exist, an illegal cross-tier call, a skill the tier cannot see, clearance above the group's ceiling, `restricted` without a justification, a user agent with any model or clearance |
| agentd, per request | at run | an ungranted model, tool, peer or skill; a document above the caller's clearance; a name not in the tree, or held by another live connection, or claimed from the wrong uid |
| systemd, per agent unit | at run | memory and CPU above the manifest's quota; any socket except `AF_UNIX` (`RestrictAddressFamilies`, `IPAddressDeny=any`); writes outside the unit's own state (`ProtectSystem=strict`); syscalls outside `@system-service` |

The systemd row is what makes the agentd row complete: an agent cannot open a
TCP connection of its own, so it cannot reach the runner, a peer, or the network
except through the broker. The broker's audit log is therefore a record of what
an agent *did*, not of what it chose to route through the broker.

Refusals carry a reason and are never retried. A task denied by policy says
which rule refused it — and says so before checking whether the target is
running, so a caller with no right to reach an agent does not learn whether it
is up.

## Tiers

- **user** — human surfaces. No model grants, no clearance above `public`. The
  console runs as the `user/shell` agent's uid; a person operating it borrows
  the console's grants, never their own.
- **app** — domain experts. Hold model, tool and document grants. Call the
  peers they name, and only app peers.
- **system** — keep the rest alive and honest. May call any tier. Must be
  `evolution.mode = "frozen"`.

## Skills

Procedures agents load, at the same three levels, ordered by privilege: `user`
is the top and least privileged, `system` the bottom and most privileged. **A
tier reads skills at its own level and every level above it, never below.**
Skill names are validated before they touch a path, and the resolved file must
sit inside its level — `../system/recover` is not a way in. On the image each
agent unit also has the levels below its tier in `InaccessiblePaths`, in both
store copies, because the store is readable by every process: without that, an
app agent could `cat` a system skill agentd would refuse to give it.

`protected = true` marks a skill as changed by human commit only.
`skills/system/recover` is protected: it is the procedure for when the agents
themselves are what broke.

## Documents

Clearance is granted to a **group** (`groups.toml`), and an agent may hold at
most its group's level. agentd holds the document store and compares each
document's classification against the caller's clearance. A listing omits what
the caller cannot open, because a title is a disclosure too.

## Protocol

Newline-delimited JSON over a Unix socket, one request per line, at most 1 MiB.
Operations: `register`, `discover`, `task` / `next_task` / `reply`, `infer`,
`skill`, `document` / `documents`, `tool`, `status` (system only). Discovery is
by card skill, so an agent finds a capability instead of hardcoding a peer.

## Language

Mojo first. Every agent entrypoint is a `main.mojo`, and every `.mojo` file in
the repo compiles (`make mojo-build`, and in CI). The broker's body, the base
library and the tooling are Python behind interop, because Mojo 1.0's standard
library has no `json`, `argparse`, `http` or `regex`, and a Mojo `def` cannot be
passed to Python as a callback.

## Designed, not built

Kept here so the plan stays visible without being mistaken for a property.

- **MCP for tools.** Tool grants are enforced by name today; there is no MCP
  transport, and a granted tool has no implementation bound
  (`Tool.run` raises, by design, until a deployment supplies one).
- **A2A task protocol.** Cards and tasks exist in AINIX's own NDJSON protocol;
  it is A2A-shaped, not A2A.
- **OCI containers per agent, network namespaces, CDI.** Agents run as
  hardened systemd units, which gives uid, cgroup and address-family isolation
  but not a separate root filesystem or network namespace.
- **Mojo on the image.** The image runs agents through
  `agents/lib/run_agent.py`, because the Mojo toolchain is not in nixpkgs.
- **Accelerator profiles on hardware.** NVIDIA and AMD profiles evaluate (CI
  checks all four configurations) and have never booted.
- **Supervision beyond systemd.** Restart and backoff are systemd's; agentd
  does not yet circuit-break a crash-looping agent.

## The shell is an agent

The login shell is `user/shell`, subject to every rule above. Commands execute
directly through a real `/bin/sh`; only input that fails to parse becomes intent
and goes to `app/shell-expert`, which returns a plan the human confirms.
`/bin/sh` stays on the image and stays a valid login shell — a system whose only
interface is an agent is a system you cannot repair when the agent is what
broke.
