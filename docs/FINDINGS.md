# Findings

Measured on an Apple M5 (10 cores, 32 GB), Docker Desktop, native `linux/arm64`.
MAX version 26.5.0.

## What works

- **MAX runs natively on arm64 Linux.** `max` 26.5.0 publishes
  `manylinux_2_34_aarch64` wheels, so the runner builds and runs on Apple
  Silicon without emulation. Modular's own containers are amd64-only, which is
  why AINIX builds its own image rather than deriving from `modular/max-full`.
- **Runner image: ~1.6 GB**, containing MAX, its Mojo kernel cache, and nothing
  else — no compiler, no package manager, non-root uid 10001.

## Dead ends, and what they cost

### Gemma cannot run on CPU under MAX 26.5

The original target was Gemma 2B. Three separate walls, in order:

1. `Gemma2ForCausalLM` is **not in the registry at all** — MAX 26.5 ships
   `gemma3`, `gemma3multimodal` and `gemma4`, but no Gemma 2.
2. Gemma 3 loads, then fails:
   `The encoding 'bfloat16' is not compatible with the selected device type 'cpu'` —
   and bfloat16 is the *only* encoding Gemma 3 declares.
3. The GGUF route fails earlier still:
   `quantization_encoding of 'q4_k' not supported by MAX engine` for that
   architecture.

Enumerating the registry settles it: of 82 architectures, the ones declaring
`float32` are Llama, Qwen2/3, Phi3, Olmo, Mamba, MPNet and a few others.
**Gemma is not among them.** Gemma on AINIX therefore waits for the GPU phase,
where bfloat16 is available. This is a MAX capability boundary, not a bug in the
image.

### bfloat16 weights cannot be cast on CPU

Asking for `--quantization-encoding float32` against a bf16 safetensors repo
fails with `Cannot cast from 'float32' to 'bfloat16' on device ... cpu`. The CPU
backend cannot read bf16 weights at all, so "download a bf16 model and run it in
fp32" is not available. CPU inference means **q4_k GGUF weights**, and the
architecture must declare `q4_k` — in practice, Llama.

### The GGUF repo must carry a tokenizer

`--model-path <gguf-repo>` fails with `Failed to load tokenizer` when the repo
holds only `config.json` and `.gguf` files. `--weight-path` is resolved relative
to the model repo, so a bare filename pointing at a *different* repo also fails.
The working shape is: `--model-path` at the full safetensors repo (for config and
tokenizer) and `--weight-path` at an **absolute local path** to the GGUF.

### MAX JIT-compiles Mojo kernels at first import, and needs a C compiler

First import of `max.pipelines` shells out to `mojo build`, which fails with
`unable to find suitable c compiler for linking` unless `clang` is present, and
with `PermissionError: … __mojocache__` when running unprivileged against a
root-owned site-packages.

Both are wrong for an immutable image, so the build warms the cache in the
**builder** stage — where clang is installed and the tree is writable — and the
runtime stage ships the resulting `.so` files with no toolchain at all. This is
a general lesson for the distro layer: **a runtime that compiles on first use
must be warmed at build time, or the immutable image is a lie.**

### q4_k on aarch64 crashes the Mojo backend

The one remaining CPU route — Llama with q4_k GGUF weights, the arch's own
default encoding — gets past config validation, builds the graph in 0.2 s, then
dies during codegen:

```
ERROR: Worker crashed (Aborted), shutting down...
In function: quantization::qmatmul_k::_matmul_Qb_K[...]
```

An LLVM instruction-selection failure inside MAX's quantized matmul kernel on
arm64. Not a configuration problem — nothing on the caller's side can avoid it.

### Verdict on MAX-on-CPU-aarch64

**Unusable for text generation in 26.5.** Every path is closed: bfloat16 is
rejected by the CPU device, bf16 weights cannot be cast to float32, and the
q4_k kernel does not compile. A float32 embedding model (BERT) did get past
validation but was still compiling after three minutes and was abandoned.

MAX stays the runtime for the GPU phase, where all of this is the supported
path. It is not the CPU runtime today.

## Engine fallback

The runner contract — OpenAI-compatible API on :8000, same env vars, same
volumes — is engine-independent. `runtime/Dockerfile.llamacpp` puts llama.cpp
behind it so CPU work proceeds while MAX waits for GPU hardware:

```bash
make image ENGINE=llamacpp && make run && make smoke
```

## Measured — llama.cpp, 8 threads, Apple M5 CPU, Q4_K_M

| model | generation | prompt | weights | smoke |
|---|---|---|---|---|
| `gemma-3-1b` | 76.7 tok/s | 93–177 tok/s | 769 MB | PASS |
| `qwen3.5-0.8b` | **101.6 tok/s** | 407–421 tok/s | 508 MB | PASS |

Runner image is 96 MB either way.

### Reasoning models return an empty answer unless thinking is disabled

Qwen3.5 failed the smoke test on first run — `finish_reason: length`, empty
`content`, and the entire token budget spent in `reasoning_content`. Raising
`max_tokens` from 64 to 512 did not fix it; the model simply thought for longer.

```json
"chat_template_kwargs": {"enable_thinking": false}
```

turns it into a normal instruct model — `finish_reason: stop`, an answer in
`content`, no reasoning at all. `test/smoke.sh` sends this now.

Worth stating as a system-level rule rather than a test detail: **an agent that
wants an answer must ask for one.** Any AINIX agent calling a reasoning model
through the OpenAI API gets an empty string unless it either disables thinking
or budgets tokens for a chain it will then throw away. `app/shell-expert`, which
must return a JSON contract, should always disable it.

The MAX runner image, for comparison, is 1.65 GB — it carries the Mojo kernel
cache, which is the price of a compiler-based runtime and buys nothing until
there is a GPU to compile for.

## Models checked against MAX's registry

| model | arch | CPU under MAX? |
|---|---|---|
| `google/gemma-2-2b-it` | `Gemma2ForCausalLM` | no — arch absent from 26.5 entirely |
| `unsloth/gemma-3-1b-it` | `Gemma3ForCausalLM` | no — bfloat16 only |
| `google/gemma-4-E2B-it` | `Gemma4ForConditionalGeneration` | no — bfloat16 / float16 / float4, no float32 |
| `Qwen/Qwen3.5-0.8B`, `-2B` | `Qwen3_5ForConditionalGeneration` | declares float32 — the most promising untested CPU candidate |
| `openbmb/MiniCPM5-1B` | `LlamaForCausalLM` | same q4_k path as Llama 3.2, so the same arm64 codegen crash |
| `OuteAI/Lite-Oute-1-300M` | `MistralForCausalLM` | no — bfloat16 only, despite fp32 weights on disk |
| `Qwen/Qwen3-0.6B` | `Qwen3ForCausalLM` | declares float32, but bf16 weights cannot be cast |
| `unsloth/Llama-3.2-1B-Instruct` | `LlamaForCausalLM` | q4_k accepted, then crashes codegen |

Gemma 4 is the one to revisit first on GPU: `float4_e2m1fnx2` support means MAX
has a genuinely fast path for it there.

## Still Python, not yet Mojo

Tracked here per the Mojo-first rule. Nothing has moved yet — the agent plane is
scaffolded, not implemented.

| Piece | Language | Why |
|---|---|---|
| `scripts/check_agent.py` | Python | build-time tool, never on the hot path |
| `agents/system/firstboot/firstboot.py` | Python | interactive console UI, runs once at boot; not on any hot path |
| agent MCP/A2A plumbing | planned Python behind interop | JSON/HTTP libraries |
| `agentd` broker path | planned Mojo | latency-critical, one hop per call |

## Not yet measured

tokens/s, cold start, agent hop overhead, tuned-vs-stock kernel. Phase 5.

## Mojo 1.0 and MAX on the M5 — measured 2026-08-26

The toolchain was never installed before now, so the four `main.mojo` agent
entrypoints had never been compiled. `pip install modular` into `.venv-mojo`
provides both binaries — no pixi needed:

```
Mojo 1.0.0 (ed45d567)   MAX 26.5.0
```

### Every agent entrypoint was written in obsolete Mojo

All four failed to parse. Mojo 1.0 removed a lot of what a pretrained model
reaches for by reflex — `fn` is gone entirely, `alias` became `comptime`, and
stdlib imports need the `std.` prefix (`from std.python import Python`, not
`from python import Python`). All four compile now.

### A Mojo callback cannot be handed to Python

```
error: value passed to 'args' cannot be converted from
       'def handle(task: PythonObject) raises thin -> PythonObject'
       to 'PythonObject'
```

`agent.serve(handle)` — register a handler, let the library call it — is not
expressible across the interop boundary. The agents now run a **pull loop**
instead: `agent.next_task()` / `agent.reply(...)`, with Mojo owning control
flow and Python providing primitives. This is a better shape for the agent
plane anyway (the tier's own code decides when to block), but it was forced,
not chosen.

### What Mojo's stdlib has, and what scripting still needs Python for

Present: `subprocess`, `os`, `pathlib`, `io`, `time`, `logger`, `random`,
`tempfile`, `testing`, `ffi`, `gpu`, `python`.
**Absent: `json`, `argparse`, `http`/`net`, `regex`.**

Every script in this repo is JSON plus CLI arguments plus HTTP, which is
exactly the three the stdlib does not cover. Mojo-first therefore means Mojo
owns the entrypoint and the control flow, with `tomllib`/`json`/`argparse`
reached through interop — not that the Python disappears.

### MAX does not run a model on this machine

Native macOS arm64 wheels install and see the GPU (`accelerator_count() == 1`),
but nothing generates:

| path | result |
|---|---|
| `--devices gpu`, Llama-3.2-1B | `Metal Compiler failed to compile metallib` |
| `--devices gpu`, Qwen3.5-0.8B | graph compile fails in `log_probabilities.py` |
| `--devices cpu`, default | `compatible weights cannot be found for 'q4_k'` — CPU defaults to q4_k and wants GGUF in the same repo |
| `--devices cpu --quantization-encoding float32` | `Cannot cast from 'float32' to 'bfloat16' ... 'bfloat16' is not supported on this device` |

The Metal failure is not model-specific — it kills the arch MAX supports best.
So llama.cpp stays the local runtime, and MAX remains the target for the GPU
box, where the CUDA path is the one Modular actually exercises.

### Fine-tuning cannot move to Mojo

`max/python/max/nn` is inference layers only — attention, kv_cache, sampling,
quant. There is no optimizer, no loss, no backward pass anywhere in the MAX
tree. `max.experimental.torch` is a **custom-op bridge**
(`CustomOpLibrary`, `graph_op`): it lets a Mojo kernel be called from inside a
PyTorch graph. That is the one honest way Mojo participates in training today —
write a hot kernel in Mojo, keep the training loop in PyTorch/MLX.

`training/train.py` therefore stays Python. Claiming otherwise would mean
writing an autograd engine, which is not what this POC is for.

## The image boots — measured 2026-08-26

```
TIME_TO_PROMPT=5s
```

Five seconds from `qemu-system-aarch64` to AINIX asking which model to run,
on the M5 with HVF:

```
AINIX — first boot
  Checking network… connected
  Default model: gemma-3-1b  (769MB, smallest thing that still follows instructions)
  This machine: 8 GB RAM
```

Kernel 6.18.2, 64 MB. Initrd 736 MB — the entire system closure as a squashfs,
which is what makes a diskless boot possible.

### Building a disk image needs KVM; a RAM boot does not

`nixos-generators`' qcow format ends in a VM that installs the bootloader:

```
error: Cannot build 'nixos-disk-image.drv'.
       Required features: {kvm}   Available features: {benchmark, big-parallel, nixos-test, uid-range}
```

Docker Desktop on macOS exposes no KVM, so that last step cannot run here. The
netboot output — kernel + initrd + squashfs — sidesteps it completely and boots
the *same configuration*, so the boot test is real. The qcow2 path is unchanged
and will build on any Linux host with KVM.

### Three boot failures, each a real configuration bug

1. **No console output at all.** `console=ttyAMA0 console=tty0` — the *last*
   `console=` wins for `/dev/console`, so the whole boot log went to a virtual
   screen nobody was watching. Reversed the order.
2. **Emergency mode on `/boot`.** `disk.nix` defined an ESP mount that a
   RAM-booted system has no reason to have, and the failed mount took Local
   File Systems down with it. The layout now sits behind `ainix.disk.enable`,
   off for netboot.
3. **First boot asked its question where nobody could answer.** `TTYPath` was
   hardcoded to `/dev/tty1` on a serial-only machine. It is now
   `ainix.firstboot.tty`, and the service conflicts with `serial-getty@` as
   well as `getty@` — otherwise the login prompt races it for the terminal.

### The runner is a systemd service, not a container, in v1

The architecture says agents are OCI containers under crun. The single shared
model runner is not an agent, needs no per-agent sandbox, and running it as a
hardened systemd unit (`DynamicUser`, `ProtectSystem=strict`, `SystemCallFilter`,
device access only on GPU profiles) keeps the image fully declarative with no
registry pull at boot. The container path arrives with `agentd`, which is what
actually needs the sandboxing. Recorded here so the deviation is visible.

### The GPU profiles are unverified

`profiles/nvidia.nix` and `profiles/amd.nix` are written from documented
interfaces and have never booted — there is no such hardware attached to this
machine. They evaluate; that is all that can honestly be claimed.

## The fine-tune ran — measured 2026-08-26

1254 steps, 2 epochs over 2507 records, LoRA r=16 on all 24 layers, MLX on the
M5 GPU. Loss 1.9 → ~0.5, 3.04 GB peak, adapter 29 MB.

### It changed the model's behaviour, visibly

Same prompt, same sampler, adapter on and off:

```
BASE   As an AI assistant, I do not have direct access to your local
       filesystem or the specific contents of your /var/log directory…

TUNED  <reply>
       ls /var/log | sort -r | head -20
       </reply>
```

The base model refuses and lectures; the tuned model answers with a command.
That is the fine-tune working. Everything wrong with the answer after that is
the dataset, not the training.

### The dataset teaches four different output shapes

```
  1178  47.0%  json contract  {"command":…,"explain":…,"mutates":…}
   640  25.5%  prose
   556  22.2%  bare command
   133   5.3%  <reply> wrapper
```

The model picked the `<reply>` wrapper — 5% of the data — over the contract
that `app/shell-expert` actually parses. With four shapes competing, which one
wins is close to arbitrary. **Normalising every record to the contract is worth
more than any hyperparameter change here.** The `<reply>` records should not
survive normalisation at all.

The command it produced is also wrong: `ls /var/log | sort -r | head -20` sorts
by *name*, not size. Nothing in the reward loop checks that an answer is
*correct*, only that it *runs* — `sort -r` runs fine. Verifying exit status
catches broken commands, not wrong ones.

### The first attempt OOM'd, and the reason was avoidable

```
RuntimeError: [METAL] Command buffer execution failed: Insufficient Memory
```

Died at step 344 with the model runner, a Mojo agent, and three stray sandbox
containers all holding memory. Freeing them and dropping `--max-seq` from 2048
to 512 fixed it — the data never needed 2048 (median record ~90 tokens, p95
195, max 533), so the rest was reserved for nothing.

### GGUF export failed, so the runner cannot serve this model yet

```
RuntimeError: Unsloth: Failed to convert text model to GGUF …
              unsloth_convert_hf_to_gguf.py --outtype bf16
```

A 529 MB `q4_k_m.gguf` was left behind by the failed run and is **corrupt** —
loading it into llama.cpp produces token soup:

```
>] vorba-0聊城8f126 =^3^  }12+cticابعıkxel reputed11m{-{textitezerar…
```

Quarantined to `/tmp/corrupt-export.gguf`. A partial export that loads without
complaint is worse than one that fails loudly, so the conversion step needs an
integrity check before anything is written to the weights cache. The adapter
itself is fine and runs under MLX; only the llama.cpp path is blocked.

## Validation on a held-out benchmark — 2026-08-26

The model trained on all 2507 records with no split, so nothing in
`training/data/` can measure it. Validation uses the **test split of NL2Bash**
(`dilkushsingh/NL2Bash`, MIT) — a benchmark from a source that was never in
training — with any prompt overlapping the training data excluded anyway.

60 held-out prompts, same sampler, adapter off and on:

| | answers | contract | runs | same utility |
|---|---|---|---|---|
| base | 56/60 | 55/60 | 8/60 | 10/60 |
| **tuned** | **60/60** | 54/60 | **27/60** | **39/60** |

Same-utility 10 → 39 is z ≈ 5.4. Not noise.

### What each column is, and is not

- **answers** — produced a command instead of refusing.
- **contract** — used the `{command, explain, mutates}` shape.
- **runs** — executes cleanly in the sandbox, the same reward environment
  `synthesize_docker.py` uses. **This under-counts.** `touch /testbed/test.txt`
  is the right answer and fails because the sandbox has no `/testbed`. It also
  over-credits: `ls | sort -r` runs fine and answers the wrong question.
- **same utility** — same base command as the reference (`cp` vs `cp`). A weak
  proxy for correctness, reported as one rather than dressed up as accuracy.

### The format problem was a prompt problem, not a training problem

An earlier note here said the dataset taught the model the wrong output shape,
on the evidence of one ad-hoc generation that came back wrapped in `<reply>`.
That test used a bare system prompt. With the system prompt that actually asks
for the contract, base and tuned both produce it — 55 and 54 of 60. The shape
mix in the data (47% contract, 25% prose, 22% bare, 5% `<reply>`) is still
worth normalising, but it is not what the fine-tune fixed and not what was
broken.

What the fine-tune actually fixed is the answer. The base model formats
beautifully and is wrong: 55/60 well-formed contracts, 10/60 right utility.

```
Q: list all currently open files       ref: lsof
   base : "list all currently open files"     (echoed the question)
   tuned: ls -la                              (still wrong, but a command)

Q: create a copy of /testbed/hello.php at /testbed/hello-COPY.php
   base : "create"
   tuned: cp -r /testbed/hello.php /testbed/hello-COPY.php
```

Reproduce with `training/evaluate.py` (Mojo entrypoint in `evaluate.mojo`);
full per-prompt output in `docs/eval.json`.

## An outcome-based reward, and the real correctness number

The reward this repo started with asks "did it exit 0". That cannot tell
`sort -r` from `sort -rn` — both run, one answers the question. `training/reward.py`
compares *effects* instead: candidate and reference each run in an identical,
freshly seeded container, and what they print and what they leave on disk is
compared.

```
1.0  equivalent   same stdout and same filesystem effect
0.6  plausible    ran cleanly, different effect
0.0  broken       failed to parse, failed to run, or on the refuse list
```

Graded, not binary, because rejection sampling needs to rank rather than only
filter.

### The bug that would have made it useless

The first version hashed stdout as `sort | md5sum`. That scored
`ls /var/log | sort -r` and `ls -S /var/log | head -20` **equivalent** — the
exact pair it exists to separate. Ordering *is* the answer for half these
questions; normalising it away rebuilds the flaw it was meant to fix. Hashing
verbatim gives 0.6, correctly.

### Re-validated with a real correctness column

| | answers | contract | runs | same utility | **correct** |
|---|---|---|---|---|---|
| base | 56/60 | 55/60 | 8/60 | 10/60 | **5/60** |
| tuned | 60/60 | 54/60 | 27/60 | 39/60 | **22/60** |

8.3% → 36.7%. The weaker columns flattered both models: `runs` counts commands
that execute while answering the wrong question, and `same utility` counts
`cp -r` as `cp`. Effect-equivalence is the number to move.

### Batched probing, because container startup is the cost

`probe_many()` re-seeds the fixture between commands inside **one** container
— 40 per invocation. Scoring a few hundred candidates one container at a time
would turn minutes into an hour.

## Free-tier rate limits: back off together, then hand off

The first distillation run logged **624 `HTTP Error 429`** and degraded as it
went — chunk 1 produced 18 teacher-equivalent records, chunk 2 produced one.
The good teacher was being starved, so almost everything fell back to
reference-anchored.

Two causes, two fixes.

**Per-call retry loops do not share a limit.** Six workers each retried
independently and walked back into the limit together. The cooldown now lives
in a module-level table keyed by model, so one worker's 429 holds all of them
off. Strikes accumulate across calls and decay only on success, so a model
that is genuinely exhausted stops being asked rather than being asked more
slowly. `Retry-After` is honoured when the server sends it, and every wait
carries ±25% jitter.

**Waiting was the first resort instead of the last.** `ask_any()` orders the
teacher pool by how long each has left to cool and takes the first ones that
are free. With six free models in the pool, a 429 costs a handoff rather than
a stall.

| | 429s logged | first chunk |
|---|---|---|
| before | 624 | 18 equivalent / 19 anchored |
| after | 0 | 21 equivalent / 16 anchored |

The progress line now names which teachers are cooling, so a pool quietly
collapsing to one model is visible rather than inferred later from the
`teacher` field.

## Normalising the dataset fixed the format and not the answers — 2026-08-27

The data taught four competing output shapes. `training/normalize.py` converts
them to one — wrapping bare commands, unwrapping `<reply>`, lifting fenced
commands out of prose, dropping records that claim to be commands and are not
usable as one, and leaving genuine Q&A in prose because forcing it into a
command contract would invent a command the source never gave.

2507 records plus 333 distilled became 2528: **2309 contract, 219 prose**,
against 1178 contract before. Retrained on that, same recipe, same held-out 60:

| | contract | runs | same utility | **correct** |
|---|---|---|---|---|
| base | 55/60 | 8/60 | 10/60 | **5/60** |
| v1 (mixed shapes) | 54/60 | 27/60 | 39/60 | **22/60** |
| v2 (normalised + distilled) | **58/60** | 25/60 | 36/60 | **20/60** |

Format compliance improved, 54 → 58. **Correctness did not**: 22 → 20 is well
inside noise at n=60. The normalisation did exactly what it was supposed to and
that turned out not to be the bottleneck — which the earlier correction already
implied, since the base model formats at 55/60 while answering 5/60 correctly.

The 333 distilled records did not help either, and the reason is visible in
their own metadata: 296 of them are `reference-anchored`, meaning the teacher
never matched the reference and the record is NL2Bash's own answer with a
borrowed explanation. That is correct data, but the model already had 2507
records of correct-looking commands. It is not new signal.

**What this rules out.** More data of the same kind, and cleaner formatting of
the same data, do not move effect-equivalence. The two levers left are a
teacher that actually beats the reference often enough to teach something
(the equivalent rate is 65% in the first chunk of a run and decays as the
endpoint saturates), and training against the outcome reward directly rather
than on its filtered output.

## Four runs of a model designing an agent org — 2026-08-27

Same brief, same model (MiniMax M3), four generations through
`scripts/generate_org.py`. The interesting result is not that it works; it is
*which* rules it breaks.

| run | agents | validator errors | `restricted` | what broke |
|---|---|---|---|---|
| 1 | 14 | 16 | 4/14 | every peer written `knowledge.broker`, not `app/knowledge-broker` |
| 2 | 10 | 1 | 5/10 | user console granted an app-level skill |
| 3 | 8 | 0 | 5/8 | nothing — but over-classified badly |
| 4 | 8 | 7 | 3/8 | six app agents naming the user console as a peer |

### It gets attributes right and relationships wrong

Tier, group, and the clearance ceiling passed in every run. What failed, every
time, was **relational**: which agent may name which, and at what level a skill
has to live for its holder to see it. The model reasons well about a single
agent in isolation and poorly about the edges between them — so a generated org
is worth having only alongside something that checks the graph.

The peer-direction error is the most persistent. Run 4 had six app agents
listing `user/console` as a peer, which inverts the whole design: the console
asks app agents for work, never the reverse. The contract says so in one line,
and the model overrode it four times out of four, presumably because "everyone
reports to the console" is the shape orgs usually have.

### Instruction did not fix over-classification. A check did.

Run 3 put five of eight agents at `restricted` — finance, engineering, people —
after the contract was amended to say, explicitly, that commercial secrecy is
`confidential` and `restricted` is for material whose leak harms a person. The
instruction made it *worse* than run 2.

What worked was making the top level cost something. `check_agent.py` now
requires `documents.justification` — one sentence naming the material — for any
agent at the highest level:

```
error: app/librarian: clearance 'restricted' requires documents.justification
       naming the material that needs it — credentials, personal data, or
       legal matter, not commercial secrecy
```

Run 4, with that rule in the contract: `restricted` fell from 5/8 to 3/8, and
two of the three carried a real justification. The third was caught.

The rule immediately found over-classification in the **hand-written** ACME
example too — `librarian` had `restricted` with no argument for it — and three
Globex engineering agents that were `restricted` for commercial secrecy and are
now `confidential`. Over-classifying is free until something makes it cost a
sentence; nobody is ever blamed for granting too much.

### The repair layer must not hide the error

`normalise_peers()` rewrites mechanically wrong references — a dot for a slash,
a bare name — and leaves anything that resolves to nothing broken. In run 4 it
turned `app/console` into `user/console`, which the tier rule then rejected as
an illegal edge. That is the correct layering: the repair made the reference
resolvable, and the rule that should catch it did.

## Clearance is now enforced, not merely validated — 2026-08-27

Manifests declared `documents.clearance` and the validator checked it against
the group ceiling, but nothing enforced it at runtime. A rule only a validator
checks is a comment with a test attached.

`agentd` now brokers documents the same way it brokers models: it holds the
store, compares each document's classification against the requester's
clearance, and audits the decision. Agents never open a file.

`test/clearance-policy.sh` runs it against the ACME example, whose agents span
every level — 11 assertions, all passing:

```
  ok   public agent sees only the public document           1
  ok   internal agent sees public + internal                2
  ok   confidential agent adds the roadmap                  3
  ok   the librarian sees everything it guards              4
  ok   marketing may NOT read the roadmap                   DENIED
  ok   the scout that reads the web gets nothing internal   DENIED
  ok   nobody but the librarian reads personal records      DENIED
  ok   ungranted tool is refused                            DENIED
```

### A listing shows only what the caller could open

`documents` filters rather than marking entries as forbidden. A confidential
document titled "acquisition-of-globex" discloses the acquisition whether or
not the body opens, so an agent that cannot read it does not learn it exists.

### Clearance is the agent's, never the human's

`may_read_document` looks only at the calling agent. A person cleared for
everything does not lend that clearance to an agent by typing into it — the
console holds `public` precisely because it is what an attacker reaches first.

Tool grants are enforced on the same path: `agent.tool(name)` asks agentd, and
an ungranted tool raises `Denied` before any implementation is bound. The grant
is the permission; a deployment supplies the code.
