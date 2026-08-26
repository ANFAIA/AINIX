# AINIX

A minimal, AI-first Linux distribution. The structure of Android, with the
JVM/ART layer replaced by **MAX + Mojo**, the app layer replaced by **agents**,
and AOSP's build system replaced by **Nix**.

Two ideas hold the whole thing together:

1. **Every process is an agent** — a domain expert with exactly the models and
   tools its manifest grants, and nothing else. Including the login shell.
2. **Nix is the memory** — an agent's identity is the hash of what it is built
   from, so evolution is a chain of derivations and rollback is free.

## Layers

| Android | AINIX |
|---|---|
| Bootloader | UKI — kernel + initrd + cmdline in one blob |
| Linux kernel | Linux kernel, minimal config, AI-tuned parameters |
| Vendor HAL | Accelerator profile — driver per vendor, exposed via CDI |
| ART / Zygote | MAX + Mojo |
| APK / app sandbox | Agent — OCI image, own uid, netns, cgroup |
| Manifest permissions | `agent.toml` — nothing undeclared is reachable |
| Binder / ServiceManager | `agentd` — registry, discovery, capability broker |
| AOSP build | Nix flake |

## Status

Phase 1 works: Gemma 3 1B answers on CPU at **76.7 tok/s** on an Apple M5.

That runner is llama.cpp, not MAX. MAX 26.5's CPU backend cannot serve text
generation on aarch64 — every encoding path is closed and the q4_k kernel
crashes the Mojo backend during codegen. MAX remains the runtime for the GPU
phase, which is its supported path. The runner contract is engine-independent
by design, so this swap cost one Dockerfile. Full detail, including which
models were checked against MAX's registry, is in
[docs/FINDINGS.md](docs/FINDINGS.md).

## Quick start

```bash
make fetch MODEL_NAME=gemma-3-1b   # 769 MB
make image                         # llama.cpp runner (96 MB); ENGINE=max for the MAX one
make run
make smoke                         # asserts a real chat completion
make bench                         # tokens/s
```

## First boot

```bash
make firstboot
```

Asks two things, in this order: is there a network, then which model this
machine should run. States the default, offers the catalog grouped by what the
hardware can actually take, and downloads nothing without a choice. No network
is a supported outcome — it records the choice and drops to a shell rather than
trapping the user in a wizard. See
[agents/system/firstboot/](agents/system/firstboot/README.md).

## Models

```bash
make models                      # the catalog: three local tiers + remote providers
make fetch MODEL_NAME=qwen3-1.7b # download one
make run GGUF=Qwen3-1.7B-Q4_K_M.gguf
```

Three local tiers — 1–3B, 8–12B, 20–30B — plus OpenAI/OpenRouter entries for
work the local ones cannot do. A remote model is still a named grant: the API
key stays with `agentd`, never enters an agent's namespace, and every remote
call is audited. Remote entries ship `enabled = false`.

## Add an agent

```bash
make agent-new TIER=app NAME=my-agent
make agent-check NAME=app/my-agent
```

See [agents/README.md](agents/README.md). No central file to edit — agents are
discovered from the tree.

## Layout

```
runtime/     model runner containers — Dockerfile (MAX), Dockerfile.llamacpp
agents/      user/, app/, system/ — one directory per agent
models.toml  model runners agents may be granted
nix/         flake modules: kernel, tuning, hardware profiles, images
scripts/     new-agent, check-agent, fetch-model, list_models
docs/        ARCHITECTURE, EVOLUTION, FINDINGS
```

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the layers, and why the agent
  plane is separate from the model plane
- [docs/EVOLUTION.md](docs/EVOLUTION.md) — who may change an agent, and how Nix
  tracks it
- [docs/FINDINGS.md](docs/FINDINGS.md) — measured results and dead ends
