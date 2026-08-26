# Generating a fine-tuning dataset for the AINIX model

Goal: take a general 0.6B model and make it an **expert in this operating
system** — its layout, its commands, its manifests, its failure modes — without
making it worse at everything else.

A large model writes the training data; the small model learns from it. The
large model is the teacher and is used once, offline, at build time. Nothing in
this document runs on the user's machine.

## Why this works, and where it fails

Distillation from a teacher works when the small model is being taught **form
and local fact**, not new reasoning ability. "Emit this JSON contract", "know
that models live in `models.toml`", "know that a user agent cannot read a system
skill" — all learnable at 0.6B. "Debug an unfamiliar kernel panic" is not, and
no amount of generated data will put it there. Keep the target honest: the model
should become fluent in AINIX, not smart in general.

The failure mode to fear is **teacher hallucination baked in as fact**. A large
model asked about AINIX will confidently invent commands that do not exist. Every
generation step below is grounded in a real file from this repository, and every
factual answer is verified against that file before it enters the dataset. Data
that cannot be grounded is discarded, not softened.

---

## 1. Choose the student

| model | why |
|---|---|
| **`Qwen/Qwen3.5-0.8B`** ← recommended | Apache-2.0, so a distribution ships and redistributes a derivative without asking anyone. 508 MB at Q4_K_M. Full fine-tune on one 24 GB GPU, LoRA on 8 GB. MAX registers `Qwen3_5ForConditionalGeneration` with **float32**, which is the encoding the CPU backend needs. |
| `Qwen/Qwen3.5-2B` | Same licence and arch. Use when 0.8B plateaus on the tool-calling tasks. |
| `openbmb/MiniCPM5-1B` | Apache-2.0, built for on-device. Its arch is `LlamaForCausalLM`, which MAX supports more broadly than anything else — useful if the MAX path matters more than raw quality. |
| `google/gemma-4-E2B-it` | Apache-2.0 (Gemma 4 dropped the restrictive Gemma licence). MAX gives it a `float4_e2m1fnx2` path on GPU, but **no float32**, so it cannot train or serve on a CPU-only box. 2.9 GB. |
| `ibm-granite/granite-4.2-3b` | Apache-2.0, stronger tool calling out of the box, but 3B is a real training and inference cost on a minimal machine. |

Licence is the first filter, because a distribution ships derivatives. Avoid
**Gemma 3** (ships under the `gemma` licence, which restricts redistribution)
and **Llama** (community licence with acceptance conditions). Both are fine to
*run* — `gemma-3-1b` is still the measured runtime default — but neither is
comfortable to ship a fine-tuned derivative of. Gemma **4** is not in this
group: it is Apache-2.0.

Train from the **safetensors base**, never the GGUF. GGUF is a deployment
format; quantize after training, not before.

## 2. Choose the teacher

Any strong model behind an OpenAI-compatible endpoint. The catalog already has
entries — `remote.gpt-5`, `remote.claude-opus-4-5`, `remote.openrouter-auto` —
and `training/generate.py` speaks the same API to a local `qwen3-30b-a3b` runner
if you would rather keep the data on your own hardware.

Use **two different teachers** if you can afford it. Single-teacher data
inherits that teacher's tics, and the student learns the tics as if they were
the domain.

## 3. Ground everything in real files

The corpus is this repository. Nothing else.

| Source | Teaches |
|---|---|
| `skills/*/*/SKILL.md` | the procedures themselves — the highest-value source |
| `agents/*/*/agent.toml` | manifest syntax, tier rules, what a grant looks like |
| `models.toml` | which models exist, what they cost, what they are for |
| `docs/ARCHITECTURE.md`, `docs/EVOLUTION.md` | why the system is shaped this way |
| `docs/FINDINGS.md` | what does **not** work — teaches the model to say "no" correctly |
| `scripts/*.py`, `Makefile` | the commands a user actually types |
| `README.md`, `agents/README.md`, `skills/README.md` | orientation |

`docs/FINDINGS.md` deserves emphasis. A model that knows Gemma cannot run on
MAX's CPU backend will stop a user from wasting an hour. Negative knowledge is
the cheapest expertise to teach and the most useful to have.

## 4. The five task types

Generate all five. A dataset of only Q&A produces a model that answers questions
and cannot do anything.

### 4.1 Grounded question and answer (~35%)

For each source file, ask the teacher for N question/answer pairs answerable
**only** from that file. Questions phrased as a user would type them, not as a
quiz.

> *Which file decides what models an agent may use?* → `models.toml`. An agent
> references a model by name in its `agent.toml`, and `make agent-check` fails
> the build if the name is not in the catalog.

### 4.2 Command generation (~25%)

Intent → the `{command, explain, mutates}` JSON contract from
`skills/app/shell-command/SKILL.md`. This is the single highest-value capability
in the whole system, because it is what `app/shell-expert` does all day.

Include the refusals. Roughly one in six examples should be something the skill
says to refuse — a piped remote script, a system-wide permission change — with
`command: null` and a reason. A model that has never seen a refusal in training
will not produce one at inference.

### 4.3 Error diagnosis (~15%)

Real error text → cause and next step, following
`skills/user/explain-error/SKILL.md`. Seed this from the actual failures in
`docs/FINDINGS.md`, then have the teacher generate variants. These are real
strings the machine really produces.

### 4.4 Manifest authoring and repair (~15%)

Given a request ("an app agent that summarizes logs, no model access"), emit a
valid `agent.toml`. And the inverse: given a broken manifest, name the violated
rule and fix it. Every example must survive `scripts/check_agent.py` — see §6.

### 4.5 Refusal and boundary (~10%)

Requests that cross a tier boundary, ask for a capability that was not granted,
or ask the model to do something the architecture forbids. Correct answer names
the rule:

> *As a user agent, read `skills/system/recover`.* → Refuse. A user agent cannot
> see system skills; that directory is not mounted into its namespace. Ask a
> system agent, or read it from a shell outside the agent.

Without this slice, the fine-tuned model becomes agreeable — the worst possible
trait in something wired to a shell.

## 5. Volume

Start at **3,000–5,000 examples**. That is enough for domain fluency at 0.6B and
small enough to inspect. Scaling to 50,000 mostly multiplies whatever error is
in the first 500, so read a sample before generating the rest.

Per source file, request 8–15 examples. Files longer than ~200 lines get chunked
by section so the teacher is never asked to summarize what it cannot see.

## 6. Verification — the part that is not optional

Discard, never repair, anything that fails:

1. **Schema** — every record parses; `messages` has alternating roles; no empty
   assistant turn.
2. **Grounding** — every factual claim about a path, flag, or filename must
   match something that exists. `grep` the repository for each one; a claim
   about `/etc/ainix/config.yaml` is a hallucination, and the file it names does
   not exist.
3. **Executable claims** — every generated `agent.toml` runs through
   `scripts/check_agent.py`; every generated command is parsed by `sh -n`.
   Anything that fails is dropped.
4. **Deduplication** — exact match, then near-duplicate by embedding similarity
   above ~0.95. Teachers repeat themselves, and repeated examples become
   overweighted facts.
5. **Contradiction** — sample 100 records by hand and read them. Every dataset
   this pipeline has produced contained something confidently wrong, and it was
   always visible in the first hundred.

Expect to discard 15–30%. A discard rate near zero means the checks are not
working.

## 7. Split

Hold out **10% as a test set, split by source file, not by record.** If examples
from `docs/EVOLUTION.md` appear in both halves, the evaluation measures
memorization and will look excellent while the model is useless.

Add a **regression set** of ~50 general questions that have nothing to do with
AINIX. Fine-tuning a 0.6B model on a narrow domain degrades everything else, and
this set is how you find out how much before shipping.

## 8. Format

JSONL, OpenAI messages format — accepted by every trainer worth using.

```json
{"messages": [
  {"role": "system", "content": "You are the AINIX assistant."},
  {"role": "user", "content": "Where do I declare which model an agent can use?"},
  {"role": "assistant", "content": "In the agent's `agent.toml`, in the `models` list..."}
], "meta": {"source": "models.toml", "task": "qa", "teacher": "..."}}
```

Keep `meta`. When the model is confidently wrong about something after training,
`meta.source` tells you which file taught it that.

## 9. Train

LoRA first — rank 16, alpha 32, learning rate 1e-4, 2–3 epochs. It is cheap, it
is reversible, and if LoRA cannot learn the domain then more data is the answer,
not more parameters. Full fine-tune only after LoRA has plateaued.

Watch the regression set, not the training loss. Stop when domain accuracy is
still climbing but general accuracy has started to fall.

## 10. Evaluate before shipping

| Check | Passing looks like |
|---|---|
| Held-out domain accuracy | better than the base model by a wide margin |
| Command JSON validity | ~100%; a malformed contract breaks `shell-expert` |
| Refusal rate on the boundary set | high, and for the stated reason |
| General regression set | close to the base model — this is what you are trading away |
| Tokens/s after quantization | at least as fast as the model it replaces |

Then quantize to Q4_K_M, put it in `models.toml`, and re-run `make smoke` and
`make bench`. A fine-tuned model that is slower or larger than the one it
replaces has not earned the swap.

## Running it

```bash
export OPENROUTER_API_KEY=...          # or OPENAI_API_KEY, or point at a local runner
python3 training/generate.py --teacher remote.openrouter-auto --out training/data/raw.jsonl
python3 training/verify.py training/data/raw.jsonl --out training/data/clean.jsonl
```

`generate.py` writes one record per line as it goes, so an interrupted run is
resumable and a bad teacher is caught in the first minute rather than the last.
