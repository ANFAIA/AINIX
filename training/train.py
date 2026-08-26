#!/usr/bin/env python3
"""LoRA fine-tune the AINIX student on AINIX_NEO_terminal data.

Follows the Unsloth SFT recipe (unsloth.ai/docs/models/gemma-4/train):
FastModel -> get_peft_model -> apply_chat_template -> SFTTrainer ->
train_on_responses_only. Adapted to this repo's defaults from
training/GENERATE-DATASET.md §9: LoRA r=16, alpha=32, lr 1e-4, 2-3 epochs.

Runs on Apple Silicon (MPS) or CUDA. Test mode does a handful of steps.

    training/.venv/bin/python training/train.py --test
    training/.venv/bin/python training/train.py --epochs 2 --out models/ainix-neo-terminal
"""

from __future__ import annotations

import argparse

import torch
from datasets import load_dataset
from unsloth import FastModel, is_bfloat16_supported
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from trl import SFTConfig, SFTTrainer

BASE = "Qwen/Qwen3.5-0.8B"
DATA = "training/data/AINIX_NEO_terminal.jsonl"


# Qwen chat markers — train_on_responses_only needs them explicitly; the
# defaults in unsloth's helper are Llama-shaped and silently mask nothing here.
QWEN_INSTRUCTION = "<|im_start|>user\n"
QWEN_RESPONSE = "<|im_start|>assistant\n"


def make_formatter(tok):
    """Bind the tokenizer explicitly. It is created inside main(), so a
    module-level `formatting` would reference a name that does not exist."""

    def formatting(examples):
        texts = [
            tok.apply_chat_template(
                c, tokenize=False, add_generation_prompt=False,
            ).removeprefix(tok.bos_token or "")
            for c in examples["messages"]
        ]
        return {"text": texts}

    return formatting


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--out", default="models/AINIX_NEO_terminal-lora")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--max-seq", type=int, default=2048)
    ap.add_argument("--test", action="store_true",
                    help="20 steps only, no save — pipeline smoke test")
    args = ap.parse_args()

    model, tokenizer = FastModel.from_pretrained(
        model_name=args.base,
        max_seq_length=args.max_seq,
        load_in_4bit=True,          # QLoRA; False for 16-bit LoRA / full FT
        full_finetuning=False,
    )
    # On Apple Silicon unsloth loads Qwen3.5 through mlx-vlm and hands back a
    # Qwen3VLProcessor, not a tokenizer. Unwrap it, and only override the chat
    # template if the model does not already ship one — Qwen3.5 does.
    tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    if not getattr(tokenizer, "chat_template", None):
        tokenizer = get_chat_template(tokenizer, chat_template="qwen3")

    model = FastModel.get_peft_model(
        model,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=16,
        lora_alpha=32,              # alpha == 2r per GENERATE-DATASET.md §9
        lora_dropout=0,
        bias="none",
        random_state=3407,
    )

    ds = load_dataset("json", data_files=args.data, split="train")
    ds = ds.shuffle(seed=7)
    keep = ["messages"]
    ds = ds.remove_columns([c for c in ds.column_names if c not in keep])
    ds = ds.map(make_formatter(tokenizer), batched=True)
    print(f"dataset: {len(ds)} records from {args.data}")
    print("--- sample ---\n" + ds[0]["text"][:600])

    cfg = dict(
        dataset_text_field="text",
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        learning_rate=args.lr,
        logging_steps=1,
        optim="adamw_8bit",
        weight_decay=0.001,
        lr_scheduler_type="linear",
        seed=3407,
        report_to="none",
        max_length=args.max_seq,
    )
    if args.test:
        cfg.update(max_steps=20, save_strategy="no", output_dir="/tmp/ainix-test")
    else:
        cfg.update(num_train_epochs=args.epochs,
                   save_strategy="steps", save_steps=50,
                   output_dir=args.out + "-ckpt")

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds,
        args=SFTConfig(**cfg),
    )
    trainer = train_on_responses_only(
        trainer,
        instruction_part=QWEN_INSTRUCTION,
        response_part=QWEN_RESPONSE,
    )

    # Mask check: labels must cover assistant turns only. Unsloth's MLX path
    # (Apple Silicon) masks inside the collator and does not materialise
    # `labels` on the dataset, so this is a check where it is available rather
    # than a hard requirement.
    ex = trainer.train_dataset[0]
    if "labels" in ex:
        shown = tokenizer.decode(
            [tokenizer.pad_token_id if x == -100 else x for x in ex["labels"]]
        ).replace(tokenizer.pad_token or "", " ")
        print("--- masked (labels) sample ---\n" + shown[:400])
    else:
        print("--- mask check skipped: labels are applied by the collator "
              "on this backend (MLX) ---")

    stats = trainer.train()
    print(stats.metrics)

    if not args.test:
        model.save_pretrained(args.out)
        tokenizer.save_pretrained(args.out)
        # GGUF export for llama.cpp runtime (models.toml contract):
        model.save_pretrained_gguf(args.out + "-gguf", tokenizer,
                                   quantization_method="q4_k_m")
        print(f"saved LoRA -> {args.out}, GGUF -> {args.out}-gguf")

    print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available()
          else "mps" if torch.backends.mps.is_available() else "cpu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
