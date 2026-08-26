# train-model

LoRA fine-tune on this machine. Every step here exists because skipping it
cost a run.

## Procedure

1. **Use `training/.venv313`, never `training/.venv`.** The 3.14 venv cannot
   pickle — `Pickler._batch_setitems() takes 2 positional arguments but 3 were
   given` — so `datasets.map` dies before training starts. dill 0.4.1 does not
   fix it and conflicts with the datasets pin.
2. **Free the GPU first.** `make stop`, kill any agent, and remove stray
   sandbox containers. A run OOM'd at step 344 with
   `[METAL] Command buffer execution failed: Insufficient Memory` because the
   model runner and three containers were holding memory.
3. **Size `--max-seq` to the data, not to a round number.** Measure first:
   median record ~90 tokens, p95 195, max 533. 512 is enough; 2048 reserves
   memory for nothing and is what turned a tight run into an OOM.
4. Train:
   ```
   training/.venv313/bin/python training/train.py --epochs 2 --max-seq 512 \
     --data training/data/AINIX_NEO_terminal.jsonl --out models/<name>
   ```
5. **Check the adapter before trusting the export.** Load it with `mlx_lm` and
   generate once, adapter on and off, on the same prompt. A fine-tune that
   worked shows a visible behaviour change; one that did not shows none.
6. **Never copy a GGUF into the weights cache without loading it first.** A
   failed export left a 529 MB file that llama.cpp loads without complaint and
   answers with token soup. A partial export that loads silently is more
   dangerous than one that fails loudly.

## Known broken

`save_pretrained_gguf` fails for Qwen3.5 (`unsloth_convert_hf_to_gguf.py`
returns 1). The adapter runs under MLX; the llama.cpp path does not work yet,
so the runner cannot serve a freshly tuned model.

## When not to

Do not train to fix a formatting problem. Base and tuned both emit the JSON
contract at ~90% when the system prompt asks for it — format is a prompt
concern. Train to fix *answers*.
