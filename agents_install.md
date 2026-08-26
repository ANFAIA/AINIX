# Installing AINIX for a coding agent

Written for an agent — Claude Code or anything with a shell — that has just
cloned this repository and has to get to a working state without a human
narrating. Every command here was run on the machine this was developed on;
where something does not work, it says so rather than staying silent.

Work through it in order. Each phase ends in a check you can run, and nothing
later depends on a phase you skipped, except where it says so.

---

## 0. What you are installing

AINIX is a Linux distribution where **every process is an agent** — a domain
expert holding exactly the models and tools its manifest grants. The pieces
you can run today:

| piece | what it is | works on macOS? |
|---|---|---|
| model runner | llama.cpp in a 96 MB container, OpenAI API on :8000 | yes |
| `agentd` | registry, discovery, capability broker | yes |
| agents | Mojo entrypoints over a Python base library | yes |
| skills | procedures agents load, privilege-ordered | yes |
| bootable image | NixOS flake, kernel tuning, hardware profiles | builds in Docker, boots in QEMU |
| training | LoRA fine-tune, distillation, held-out validation | yes, Apple GPU via MLX |

---

## 1. Prerequisites

```bash
docker info >/dev/null && echo "docker ok"
python3 -c 'import sys; print(sys.version)'   # 3.13 needed for training
git --version
```

**Docker is required** for the model runner, the reward sandbox, and the image
build. Everything else degrades gracefully; Docker does not.

Optional, per phase:

| tool | needed for | install |
|---|---|---|
| `qemu-system-aarch64` | booting the image | `brew install qemu` |
| Mojo | compiling agent entrypoints | phase 4 below |
| Python 3.13 | training and evaluation | `brew install python@3.13` |

---

## 2. Run a model — the shortest path to something working

```bash
make fetch MODEL_NAME=gemma-3-1b   # 769 MB
make image                         # llama.cpp runner, 96 MB
make run
make smoke                         # asserts a real chat completion
```

`make smoke` prints `PASS` and a sentence from the model. If it does not, read
the failure before continuing — everything else assumes a working runner.

```bash
make bench    # tokens/s; expect ~77 for gemma-3-1b, ~102 for qwen3.5-0.8b on an M5
```

**Do not use `--engine max`.** MAX is in the catalog and in the Dockerfile, but
it does not run a model on macOS: the Metal backend fails to compile a metallib
even for Llama-1B, and the CPU path refuses bfloat16 weights. See
[docs/FINDINGS.md](docs/FINDINGS.md). llama.cpp is the working local runtime;
MAX is for the GPU phase.

---

## 3. Bring up the agent plane

```bash
export AINIX_SOCK=/tmp/ainix-agentd.sock AINIX_ROOT=$PWD PYTHONPATH=$PWD/agents/lib
python3 agents/system/agentd/agentd.py &
./test/agent-policy.sh          # 10 capability tests, all must pass
```

`agent-policy.sh` is the check that matters. It asserts the system **fails
closed**: a user agent refused a model, refused a system skill, refused an
unlisted peer; an app agent refused a call back down to a user agent; an
unregistered connection refused everything. If any of those pass when they
should deny, stop and fix it — a capability system that fails open is worse
than none.

End to end through a real agent:

```bash
(cd agents/app/shell-expert && mojo run main.mojo &)   # needs phase 4
python3 -c "
import sys; sys.path.insert(0,'agents/lib')
from ainix_agent import Agent
s = Agent.from_manifest('agents/user/shell/agent.toml')
print(s.peer('app/shell-expert').task('shell.ask', 'list large files in /var/log'))"
```

---

## 4. Mojo (optional, but it is the project's first language)

```bash
python3 -m venv .venv-mojo
.venv-mojo/bin/pip install modular      # provides both `mojo` and `max`
.venv-mojo/bin/mojo --version           # Mojo 1.0.0
for f in agents/*/*/main.mojo; do .venv-mojo/bin/mojo build "$f" -o /tmp/x.bin; done
```

**Your pretrained Mojo is out of date.** Mojo 1.0 removed `fn` entirely,
replaced `alias` with `comptime`, and requires the `std.` prefix on stdlib
imports. Read `mojo-syntax` and `mojo-python-interop` from
`github.com/modular/skills` before writing any Mojo here — every `.mojo` file
in this repo failed to parse until those were followed.

Two limits worth knowing before you design anything:

- Mojo's stdlib has `subprocess`, `os`, `pathlib`, `time` — but **no `json`,
  `argparse`, `http`, or `regex`**. Mojo owns the entrypoint and control flow;
  those three come through Python interop.
- **A Mojo `def` cannot be passed to a Python function.** Callback registration
  does not cross the boundary; agents use a pull loop (`next_task`/`reply`).

---

## 5. The bootable image

```bash
make os-eval     # type-check the whole NixOS configuration, build nothing
make os-build    # qcow2 — needs a Linux host with KVM
make os-boot     # boot in QEMU
```

Nix runs inside a `nixos/nix` container because this is a Mac; a named volume
keeps the store between runs.

**On macOS, `make os-build` cannot finish.** The final disk-image step runs a
VM to install a bootloader and needs KVM, which Docker Desktop does not expose.
Use the netboot output instead — kernel plus the whole closure as a squashfs
initrd, same module list, boots to the first-boot prompt in about five seconds:

```bash
docker run --rm -v "$PWD":/src -w /src -v ainix-nix-store:/nix -v "$PWD/build":/out \
  nixos/nix nix --extra-experimental-features 'nix-command flakes' \
  build .#netboot --out-link /out/netboot
```

---

## 6. Training and evaluation

```bash
python3.13 -m venv training/.venv313
training/.venv313/bin/pip install torch transformers datasets trl peft \
  accelerate unsloth mlx mlx-lm mlx-vlm
```

**Use Python 3.13, not 3.14.** On 3.14 dill cannot pickle
(`Pickler._batch_setitems() takes 2 positional arguments but 3 were given`), so
`datasets.map` dies before training starts. dill 0.4.1 does not fix it and
conflicts with the datasets pin.

```bash
training/.venv313/bin/python training/train.py --epochs 2 --max-seq 512 \
  --data training/data/AINIX_NEO_terminal.jsonl --out models/my-lora

training/.venv313/bin/python training/evaluate.py --limit 60
```

Before training, **free the GPU** — `make stop`, kill any agent, remove stray
sandbox containers. A run OOM'd at step 344 on Metal because the runner and
three containers were holding memory.

Evaluation runs base and tuned in one invocation on held-out NL2Bash. The
headline column is `CORRECT` — effect-equivalence measured by running both the
candidate and the reference in identical containers. The others flatter:
`runs` counts commands that execute while answering the wrong question.

### Teacher credentials

Never put a key in `models.toml`; the catalog is committed. Entries name an
env var, and the value goes in `.env.local`, which is gitignored:

```bash
cat > .env.local <<'KEYS'
export OPENROUTER_API_KEY='...'
export AINIX_TEACHER_KEY='...'
KEYS
chmod 600 .env.local
```

```bash
source .env.local
training/.venv313/bin/python training/distill.py --limit 400 --workers 4 \
  --per-prompt 1 --teachers remote.qwen38-local
```

---

## 7. Working in this repo

**Run it, do not describe it.** Nearly every check in this project's history
turned up a real breakage that reading the code did not: a signature mismatch,
a Python-version incompatibility, four `.mojo` files that had never once been
compiled, a GGUF that loaded without complaint and emitted noise. Claims come
from executions.

**Back up before anything rewrites data.** `training/data/` is gitignored, and
one merge destroyed ~400 verified records.

**Read the skills before doing the work they cover.** `skills/system/` holds
`train-model`, `validate-model`, `build-image`; `skills/app/` holds
`verify-command` and `distill-dataset`. They exist so the failures above are
paid for once.

```bash
make skills                     # everything, by level
make agent-check                # every manifest still legal
./test/agent-policy.sh          # the capability system still fails closed
make smoke                      # the runner still answers
```

Those four are the regression suite. Run them before claiming anything works.

---

## Known broken

| thing | state |
|---|---|
| MAX on macOS | does not run a model — Metal cannot compile a metallib; CPU refuses bfloat16 |
| GGUF export of a fine-tune | `unsloth_convert_hf_to_gguf.py` fails for Qwen3.5; adapters run under MLX only |
| `make os-build` on macOS | needs KVM; use the netboot output |
| NVIDIA / AMD profiles | evaluate, never booted — no such hardware here |
| free OpenRouter teachers | heavily rate-limited; a private endpoint is far better |
