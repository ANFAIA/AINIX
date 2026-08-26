# AINIX

A minimal, AI-first Linux distribution where **every process is an agent**.

The structure of Android, with the JVM/ART layer replaced by **MAX + Mojo**,
the app layer replaced by **agents**, and AOSP's build system replaced by
**Nix**. The login shell is an agent. The setup wizard is an agent. The thing
that keeps them alive and honest is an agent.

## Start here if you are an agent

This repository is built to be picked up by a coding agent without a human
narrating.

| file | what it gives you |
|---|---|
| [agents_install.md](agents_install.md) | every command, in order, with what does **not** work |
| [CLAUDE.md](CLAUDE.md) | house rules, the regression suite, and what not to do |
| `.claude/skills/` | `ainix-setup`, `ainix-check`, `ainix-train` |
| `.claude/settings.json` | read-only commands pre-allowed, so checks do not prompt |

```bash
make smoke                # the runner answers
make agent-check          # every manifest is legal
./test/agent-policy.sh    # the capability system fails closed
make os-eval              # the NixOS configuration type-checks
```

Those four are the regression suite. Run them before claiming anything works.

One house rule above the others: **run it, do not describe it.** Nearly every
check in this project's history turned up a real breakage that reading the code
did not — a reward function that scored two different answers identical, four
`.mojo` files that had never been compiled, a GGUF that loaded without
complaint and emitted noise.

## Two ideas hold it together

1. **Every process is an agent** — a domain expert with exactly the models and
   tools its manifest grants, and nothing else.
2. **Nix is the memory** — an agent's identity is the hash of what it is built
   from, so evolution is a chain of derivations and rollback is free.

## The agent plane

Three tiers, ordered by privilege. `user` is the top and **least** privileged;
`system` is the foundation and most privileged.

| tier | holds | may call |
|---|---|---|
| `user` | the human surfaces — shell, CLI, UI. No model grant at all. | app agents |
| `app` | the domain experts. Model and tool grants live here. | other app agents |
| `system` | keeps the rest alive and honest: registry, supervision, brokering. | anything |

`agentd` is what makes a manifest enforceable rather than advisory. **Agents
hold manifests; agentd holds addresses.** An agent with no grant for a model
cannot reach the runner because it never learns the URL — every inference and
every task is brokered, and every decision is audited with a reason.

```
user/shell  →  agentd  →  app/shell-expert  →  agentd  →  model runner
   no model grant          holds the grant       holds the URL
```

Skills follow the same ordering: a tier reads and modifies its own level and
every level *above* it, and cannot see the levels below — those directories are
never mounted into its namespace. A system agent can repair a user agent's
skills; a user agent cannot read a system skill at all.

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

## Status — measured, on an Apple M5

| | |
|---|---|
| model runner | `qwen3.5-0.8b` **101.6 tok/s**, `gemma-3-1b` 76.7 tok/s (Q4_K_M, llama.cpp, 96 MB image) |
| agent plane | 10/10 capability tests pass; end to end in 5.7 s through a Mojo agent |
| bootable image | boots to the first-boot prompt in **5 s** in QEMU |
| fine-tune | held-out correctness **8.3% → 36.7%** on NL2Bash test |

What does not work is stated as plainly: **MAX does not run a model on macOS**
— the Metal backend cannot compile a metallib even for Llama-1B, and the CPU
path refuses bfloat16 weights. llama.cpp is the local runtime; MAX is for the
GPU phase. The runner contract is engine-independent, so the swap cost one
Dockerfile. Full detail in [docs/FINDINGS.md](docs/FINDINGS.md).

## Quick start

```bash
make fetch MODEL_NAME=gemma-3-1b   # 769 MB
make image                         # llama.cpp runner, 96 MB
make run
make smoke                         # asserts a real chat completion
make bench                         # tokens/s
```

## First boot

```bash
make firstboot
```

Asks two things, in this order: is there a network, then which model this
machine should run. The catalog is grouped by what the hardware can actually
take, and each entry is tagged against the real machine — `downloaded`,
`needs network`, `too big for this machine`. No network is a supported outcome:
it records the choice and drops to a shell rather than trapping the user in a
wizard.

## Models

```bash
make models                        # the catalog
make fetch MODEL_NAME=qwen3.5-0.8b
make run GGUF=Qwen3.5-0.8B-Q4_K_M.gguf
```

Three local tiers — 1–3B, 8–12B, 20–30B — plus remote providers for work the
local ones cannot do. A remote model is still a named grant: the key stays with
`agentd`, never enters an agent's namespace, and every call is audited. Keys
live in `.env.local`, never in the committed catalog.

## Skills

A skill is a written procedure an agent loads — instructions, not code.

```bash
make skills                                  # all of them, by level
make skills TIER=app                         # only what an app agent can see
scripts/skillctl.py can user system/recover  # explain an access decision
```

`skills/system/` holds `train-model`, `validate-model`, `build-image`,
`manage-runner`, `recover`; `skills/app/` holds `verify-command`,
`distill-dataset`, `shell-command`, `summarize`. They carry failures already
paid for once. See [skills/README.md](skills/README.md).

## The image

```bash
make os-eval     # type-check the configuration, build nothing
make os-boot     # boot it in QEMU
```

Nix runs in a container because the development machine is a Mac. Building a
disk image needs KVM, which Docker Desktop does not expose — the netboot output
boots the same module list from RAM instead. See [nix/README.md](nix/README.md).

## Training

```bash
training/.venv313/bin/python training/train.py --epochs 2 --max-seq 512 \
  --data training/data/AINIX_NEO_terminal.jsonl --out models/my-lora
training/.venv313/bin/python training/evaluate.py --limit 60
```

Validation is held out — NL2Bash's test split, a source never used in training.
The headline is effect-equivalence: candidate and reference run in identical
containers and are compared on what they print and what they leave on disk.
Exit status is not correctness; `sort -r` and `sort -rn` both exit 0.

## Layout

```
agents/      user/, app/, system/ — one directory per agent, plus agentd
skills/      user/, app/, system/ — procedures agents load
runtime/     model runner containers
nix/         flake modules: kernel, tuning, hardware profiles, images
training/    dataset generation, verification, LoRA, held-out evaluation
scripts/     new-agent, check-agent, fetch-model, skillctl
test/        smoke.sh, agent-policy.sh
models.toml  the catalog agents may be granted from
```

## Docs

- [agents_install.md](agents_install.md) — setup, for an agent
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the layers, and why the agent
  plane is separate from the model plane
- [docs/EVOLUTION.md](docs/EVOLUTION.md) — who may change an agent, and how Nix
  tracks it
- [docs/FINDINGS.md](docs/FINDINGS.md) — measured results and dead ends
