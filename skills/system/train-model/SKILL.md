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

## Exporting for the runner

```
training/.venv313/bin/python training/export_gguf.py models/<name>-lora --install
```

Merges the LoRA into the **HuggingFace** base tensors directly, converts and
quantizes with the same llama.cpp build the runner uses, then serves the result
and refuses to install it unless it answers readably.

Do not use `mlx_lm fuse` + convert, and do not use unsloth's
`save_pretrained_gguf`. MLX saves conv1d weights channel-last, the converter
reads them as PyTorch layout, and every Qwen3.5 linear-attention layer comes out
transposed: the GGUF loads without an error and emits token soup. The fuse also
drops the MTP block and rewrites the tokenizer class.

Then measure the export, not just the adapter — same prompts, through the
runner: `evaluate.py --endpoint tuned http://localhost:<port>`. v2 scored 20/60
under MLX and 17/60 as Q4_K_M; the gap is quantization.

## When not to

Do not train to fix a formatting problem. Base and tuned both emit the JSON
contract at ~90% when the system prompt asks for it — format is a prompt
concern. Train to fix *answers*.
