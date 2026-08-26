# training

Turning a general 0.6B model into an expert in this operating system.

- **[GENERATE-DATASET.md](GENERATE-DATASET.md)** — the instructions: which
  student, which teacher, the five task types, verification, training, and what
  to check before shipping. Read this first.
- `generate.py` — asks a teacher model for training data grounded in this
  repository's own files. Stdlib only; resumable; writes JSONL as it goes.
- `verify.py` — the checks from §6. Discards, never repairs.
- `data/` — generated output, not committed.

```bash
export OPENROUTER_API_KEY=...
python3 training/generate.py --teacher remote.openrouter-auto --limit 3   # try 3 chunks first
python3 training/verify.py training/data/raw.jsonl
```

Start with `--limit 3` and read the output. A teacher that is going to
hallucinate does it in the first minute, and finding that out after a full run
is an expensive way to learn it.

## The student

`Qwen/Qwen3.5-0.8B` — Apache-2.0, 508 MB at Q4_K_M, full fine-tune on one 24 GB
GPU and LoRA on 8 GB, and MAX registers `Qwen3_5ForConditionalGeneration` with
float32, which is the encoding a CPU box needs. In `models.toml` as
`qwen3.5-0.8b`, with `qwen3.5-2b` as the step up.

Alternatives in the catalog, all Apache-2.0: `minicpm5-1b` (Llama arch — the
one MAX supports most broadly) and `gemma-4-e2b` (float4 fast path on GPU, but
no float32, so it cannot train or serve CPU-only).

Licence is the first filter, since a distribution ships derivatives. That rules
out **Gemma 3** (`gemma` licence, restricted redistribution — it is still the
measured runtime default, just not a training base) and **Llama** (community
licence with acceptance conditions). Gemma **4** is Apache-2.0 and carries none
of that.
