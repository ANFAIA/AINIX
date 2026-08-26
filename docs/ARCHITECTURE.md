# AINIX architecture

## The two planes

**Model plane** — a small number of shared model runners. Each is one MAX
`serve` process in a container, exposing an OpenAI-compatible endpoint. Declared
in `models.toml`.

**Agent plane** — many agents, each a process with its own uid, network
namespace and cgroup. Agents hold *grants* to model endpoints; they never load
weights.

Keeping these apart is not tidiness. N agents each loading a 1B model is N × the
memory, and on a GPU it is N × the VRAM plus context-switch thrash. One runner,
many agents, capability-scoped access.

```
  user/shell ──┐
  user/cli   ──┤ A2A tasks
               ▼
            agentd ────── registry, capability tokens, audit
               │
               ├── app/shell-expert ──┐
               └── app/summarizer   ──┤ granted endpoints only
                                      ▼
                          model runner (MAX serve, :8000)
```

## Layers, bottom up

1. **Kernel** — minimal config, parameters tuned for inference: 1 GiB hugepages
   behind the KV cache, `isolcpus`/`nohz_full` over the inference cores, IOMMU
   in passthrough, `performance` governor. Each parameter carries a comment
   saying what it buys; `mitigations=off` is offered but off by default, because
   it is a security trade-off and not a free win.
2. **Accelerator profile (the HAL)** — one Nix module per vendor pinning driver
   and userspace, emitting a CDI spec. The container image is identical across
   profiles; only the injected devices differ. This is where "install the driver
   for your hardware" lives, and it is the only vendor-specific layer.
3. **Runtime (the ART)** — MAX + Mojo. One kernel source compiles to CPU, NVIDIA
   and AMD, which is what makes layer 2 thin enough to be per-vendor.
4. **Agents (the apps)** — see below.
5. **agentd (the ServiceManager)** — registry, discovery, capability minting,
   supervision, audit.

## Agents

Three tiers with different privileges:

- **user** — human surfaces. No model grants. Callable only by humans, never by
  app agents.
- **app** — domain experts. Hold model and tool grants. Call peers they name.
- **system** — keep the rest alive and honest. Only tier that may mutate the
  registry or spawn agents. Must be `evolution.mode = "frozen"`.

The manifest (`agent.toml`) is the whole contract. Three independent layers
enforce it, so no single check is load-bearing:

| Layer | Catches |
|---|---|
| Nix, at build | a grant that is not declared, a peer that does not exist, an illegal cross-tier call |
| Kernel, at run | reaching anything not mounted in — own uid, netns, cgroup, seccomp, read-only rootfs |
| agentd, per call | an invalid or expired capability token; writes the audit record |

An ungranted model endpoint is not "denied" — its socket was never mounted, so
it is not addressable.

## Protocols

- **Agent → tool**: MCP over Unix sockets. One socket per granted tool.
- **Agent → agent**: A2A-style cards for discovery plus a task protocol for the
  call. Cards let an agent find a capability instead of hardcoding a peer.
- `agentd` brokers between schema versions so agents upgrade independently.

## Language

Mojo first, Python second. Python is the fallback where Mojo's systems and
networking story is still thin, reached through interop so the boundary is a
function call rather than another process. Which pieces are still Python — and
why — is tracked in [FINDINGS.md](FINDINGS.md); "what could not yet be Mojo" is
one of the results this POC exists to produce.

## The shell is an agent

The login shell is `user/shell`, subject to every rule above: no model grant,
own uid, one declared peer. Commands execute directly through a real `/bin/sh`;
only input that fails to parse becomes intent and goes to `app/shell-expert`,
which returns a plan the human confirms. `/bin/sh` stays on the image and stays
a valid login shell — a system whose only interface is an agent is a system you
cannot repair when the agent is what broke.
