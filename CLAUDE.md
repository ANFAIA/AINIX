# AINIX — working notes for a coding agent

A Linux distribution where every process is an agent. Read
[agents_install.md](agents_install.md) before running anything; it has the
exact commands and the things that do not work.

## House rules

**Run it, do not describe it.** Every claim about this repo comes from an
execution. The history here is a list of things that looked fine and were not:
a reward function that scored two different answers identical, four `.mojo`
files that had never been compiled, a GGUF that loaded silently and emitted
noise, a training venv whose Python could not pickle.

**Mojo first.** Agents, scripts, and tooling get a Mojo entrypoint that owns
control flow. Python is the fallback for what Mojo's stdlib lacks — `json`,
`argparse`, `http`, `regex` — reached through `from std.python import Python`.
Track what is still Python in `docs/FINDINGS.md`; "what could not yet be Mojo"
is a result, not an embarrassment.

**Your Mojo knowledge is stale.** Mojo 1.0 removed `fn`, replaced `alias` with
`comptime`, and requires `std.` on stdlib imports. Follow
`github.com/modular/skills` (`mojo-syntax`, `mojo-python-interop`) over recall.

**Read the skill before doing the work.** `skills/system/{train-model,
validate-model,build-image}` and `skills/app/{verify-command,distill-dataset}`
hold failures already paid for once.

**Back up before rewriting data.** `training/data/` is gitignored. One merge
destroyed ~400 verified records.

**Keys never enter `models.toml`.** The catalog is committed; entries name an
env var and values live in `.env.local` (gitignored, 600).

## Regression suite

```bash
make smoke                # the runner answers
make agent-check          # every manifest is legal
./test/agent-policy.sh    # the capability system fails closed
make os-eval              # the NixOS configuration type-checks
```

Run these before saying something works.

## Shape of the thing

- `agents/` — `user/`, `app/`, `system/`, one directory each. A manifest grants
  models, tools, peers, skills; nothing undeclared is reachable.
- `agents/system/agentd/` — the broker. Agents hold manifests, agentd holds
  addresses. An agent with no grant never learns the model endpoint's URL.
- `skills/` — procedures, privilege-ordered. A tier reads its own level and
  every level *above* it, never below. `user` is the top and least privileged.
- `nix/` — the bootable image: kernel config, tuning, hardware profiles.
- `training/` — dataset generation, verification, LoRA, held-out evaluation.
- `docs/FINDINGS.md` — measured results and dead ends. Append to it.

## Do not

- Do not use MAX as the local runner. It does not run a model on macOS.
- Do not measure a fine-tune on `training/data/` — the model trained on all of
  it. Use `training/evaluate.py`, which is held out.
- Do not report `runs` as correctness. It counts commands that execute while
  answering the wrong question.
- Do not copy a GGUF into the weights cache without loading it first.
