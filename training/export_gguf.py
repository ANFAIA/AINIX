#!/usr/bin/env python3
"""Merge an MLX LoRA adapter into the HuggingFace base and export a GGUF the
runner can serve — and refuse to install it unless it actually answers.

Why not `mlx_lm fuse` + convert: MLX saves conv1d weights channel-last,
[out, kernel, in], where PyTorch and the llama.cpp converter expect
[out, in, kernel]. Qwen3.5's linear-attention layers are conv1d, so the
converter reads every one of them transposed and the model emits token soup —
while loading without a single error. It also drops the MTP block while the
config still counts it (`blk.24.attn_norm.weight not found`), and rewrites the
tokenizer class to one the converter's transformers cannot load.

So the merge happens here, on the original HF tensors: for each LoRA-adapted
Linear, W += scale · (A·B)ᵀ, in float32, cast back to the base dtype. Nothing
else is touched — conv layout, MTP head, tokenizer and config stay exactly as
the base shipped them. Then llama.cpp (pinned, same build as the runner)
converts and quantizes.

    training/.venv313/bin/python training/export_gguf.py models/AINIX_NEO_v2-lora \\
        --name ainix-neo-v2 --install
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from safetensors import safe_open
from safetensors.torch import save_file

ROOT = Path(__file__).resolve().parent.parent
LLAMA_CPP = "ghcr.io/ggml-org/llama.cpp:full-b11151"   # same build as the runner
RUNNER = "ainix/runtime:cpu-llamacpp"


def merge(base_dir: Path, adapter_dir: Path, out: Path) -> int:
    cfg = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    scale = float(cfg["lora_parameters"]["scale"])

    lora: dict[str, dict[str, torch.Tensor]] = {}
    with safe_open(adapter_dir / "adapters.safetensors", "pt") as h:
        for k in h.keys():
            mod, part = k.rsplit(".", 1)                 # ...up_proj, lora_a
            # MLX names the text model language_model.model.*; the HF base
            # names it model.language_model.*.
            hf = mod.replace("language_model.model.", "model.language_model.", 1)
            lora.setdefault(hf + ".weight", {})[part] = h.get_tensor(k).float()

    out.mkdir(parents=True, exist_ok=True)
    applied = 0
    for shard in sorted(base_dir.glob("*.safetensors")):
        tensors, meta = {}, None
        with safe_open(shard, "pt") as h:
            meta = h.metadata()
            for k in h.keys():
                t = h.get_tensor(k)
                if k in lora:
                    a, b = lora[k]["lora_a"], lora[k]["lora_b"]   # [in,r], [r,out]
                    delta = scale * (a @ b).T                      # [out,in]
                    if delta.shape != t.shape:
                        sys.exit(f"shape mismatch on {k}: base {tuple(t.shape)}, "
                                 f"delta {tuple(delta.shape)}")
                    t = (t.float() + delta).to(t.dtype)
                    applied += 1
                tensors[k] = t.contiguous()
        save_file(tensors, out / shard.name, metadata=meta or {"format": "pt"})

    if applied != len(lora):
        missing = sorted(set(lora) - {k for s in base_dir.glob('*.safetensors')
                                      for k in safe_open(s, 'pt').keys()})[:5]
        sys.exit(f"applied {applied} of {len(lora)} adapter weights; "
                 f"unmatched e.g. {missing}")

    # Everything that is not a weight comes from the base, untouched.
    for f in base_dir.iterdir():
        if not f.name.endswith(".safetensors") and f.is_file():
            shutil.copy(f.resolve(), out / f.name)
    return applied


def docker(*args: str) -> None:
    r = subprocess.run(["docker", "run", "--rm", *args], capture_output=True,
                       text=True)
    if r.returncode != 0:
        sys.exit(f"docker {' '.join(args[-4:])} failed:\n{r.stderr[-1500:]}")


def answers_like_a_model(gguf: Path, port: int = 8093) -> tuple[bool, list[str]]:
    """Serve it and ask. A GGUF that loads and emits noise is worse than one
    that fails to load, so 'it loaded' is not the bar — readable answers are."""
    name = "ainix-export-gate"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, "-p", f"{port}:8000",
                    "-v", f"{gguf.parent}:/weights:ro",
                    "-e", f"LLAMA_ARG_MODEL=/weights/{gguf.name}", RUNNER],
                   check=True, capture_output=True)
    try:
        for _ in range(90):
            try:
                urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2)
                break
            except Exception:
                time.sleep(2)
        system = ('You are the AINIX assistant. Answer with ONLY a JSON object: '
                  '{"command":..., "explain":..., "mutates":true|false}.')
        outs = []
        for q in ("count the lines in file.txt", "show disk usage of /var/log",
                  "list the files in the current directory"):
            body = {"messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": q}],
                    "max_tokens": 80, "temperature": 0,
                    "chat_template_kwargs": {"enable_thinking": False}}
            r = urllib.request.urlopen(urllib.request.Request(
                f"http://localhost:{port}/v1/chat/completions",
                json.dumps(body).encode(), {"Content-Type": "application/json"}),
                timeout=120)
            outs.append(json.load(r)["choices"][0]["message"]["content"])
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    def readable(s: str) -> bool:
        s = s.strip()
        return bool(s) and sum(c.isascii() for c in s) / len(s) > 0.95 \
            and '"command"' in s
    return all(readable(o) for o in outs), outs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("adapter")
    ap.add_argument("--base", default="Qwen/Qwen3.5-0.8B")
    ap.add_argument("--name", default=None, help="output name, e.g. ainix-neo-v2")
    ap.add_argument("--quant", default="Q4_K_M")
    ap.add_argument("--install", action="store_true",
                    help="copy into the weights cache — only if the gate passes")
    args = ap.parse_args()

    adapter = (ROOT / args.adapter).resolve()
    name = args.name or adapter.name.lower().replace("_", "-").removesuffix("-lora")
    work = ROOT / "build" / "export"
    merged = work / f"{name}-hf"
    f16 = work / f"{name}-f16.gguf"
    q = work / f"{name}-{args.quant.lower()}.gguf"

    base = Path(snapshot_download(args.base))
    print(f"merging {adapter.name} into {args.base} …")
    n = merge(base, adapter, merged)
    print(f"  {n} LoRA weights applied; conv1d layout, MTP head and tokenizer "
          f"left as the base shipped them")

    print("converting …")
    docker("-v", f"{work}:/models", LLAMA_CPP, "--convert", "--outtype", "f16",
           "--outfile", f"/models/{f16.name}", f"/models/{merged.name}")
    print("quantizing …")
    docker("-v", f"{work}:/models", LLAMA_CPP, "--quantize",
           f"/models/{f16.name}", f"/models/{q.name}", args.quant)
    print(f"  {q.name}  {q.stat().st_size / 2**20:.0f} MiB")

    print("gate: does it answer? …")
    ok, outs = answers_like_a_model(q)
    for o in outs:
        print("   ", o.strip().replace("\n", " ")[:100])
    if not ok:
        print("REFUSED: the export loads but does not answer like a model. "
              "Not installed.", file=sys.stderr)
        return 1
    print("  passed")

    if args.install:
        dest = Path.home() / ".cache/ainix/weights" / q.name
        shutil.copy(q, dest)
        print(f"installed -> {dest}\nserve it:  make run GGUF={q.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
