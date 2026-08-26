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

`Qwen/Qwen3-0.6B` — Apache-2.0, so a distribution can ship a derivative without
asking anyone; full fine-tune on one 24 GB GPU, LoRA on 8 GB; and MAX supports
`Qwen3ForCausalLM`, so the same weights have a GPU path later. In `models.toml`
as `qwen3-0.6b`, with `qwen3-1.7b` as the step up.

Licensing is the reason the current runtime default (`gemma-3-1b`) is not the
training base: Gemma's terms restrict redistribution, and Llama's community
license carries acceptance conditions. Both are fine to run. Neither is
comfortable to ship a fine-tuned derivative of.
