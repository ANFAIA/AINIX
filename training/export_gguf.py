#!/usr/bin/env python3
"""Re-merge the trained LoRA into the base and export GGUF q4_k_m.

save_pretrained_gguf's llama.cpp converter asserts on Qwen3.5 because the
merged checkpoint drops the MTP block while the config lacks
`mtp_num_hidden_layers`. This script saves the merged model itself and then
runs the converter with `--no-mtp`, which is correct for an MTP-less export.
"""

import pathlib
import subprocess
import sys

from unsloth import FastModel

CONVERTER = pathlib.Path.home() / ".unsloth" / "llama.cpp" / "unsloth_convert_hf_to_gguf.py"

BASE = "Qwen/Qwen3.5-0.8B"
LORA = sys.argv[1] if len(sys.argv) > 1 else "models/AINIX_NEO_terminal-lora"
OUT = LORA + "-gguf"
MERGED = "/tmp/ainix-merged"

model, tokenizer = FastModel.from_pretrained(
    model_name=LORA,
    base_model=BASE,
    max_seq_length=2048,
    load_in_4bit=False,          # merge needs dequantized weights
)
tokenizer = getattr(tokenizer, "tokenizer", tokenizer)

model.save_pretrained_merged(MERGED, tokenizer, save_method="merged_16bit")

subprocess.run([str(CONVERTER),
    "--hf", MERGED,
    "--outfile", OUT + "/" + "AINIX_NEO_terminal-q4_k_m.gguf",
    "--outtype", "q4_k_m",
    "--no-mtp",
], check=True)
print(f"saved GGUF -> {OUT}")
