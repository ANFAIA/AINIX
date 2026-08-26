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
