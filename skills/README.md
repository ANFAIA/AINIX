# Skills

A skill is a written procedure an agent loads to do one kind of work well:
instructions, and optionally scripts it may run. Skills are data, not code paths
— adding one does not require rebuilding an agent.

```
skills/<level>/<name>/
  skill.toml     what it is, what it needs
  SKILL.md       the procedure itself
  *.sh, *.py     optional helpers the skill may invoke
```

## Levels and who may touch what

Skills live at the same three levels as agents, ordered by privilege. **`user`
is the top — closest to the human, least privileged. `system` is the bottom —
the foundation, most privileged.**

The rule is one sentence: **a tier may read and modify skills at its own level
and at every level above it, and cannot see the levels below.**

| Acting tier | user skills | app skills | system skills |
|---|---|---|---|
| **user** | read + write | not visible | not visible |
| **app** | read + write | read + write | not visible |
| **system** | read + write | read + write | read + write |

So a system agent can rewrite a user agent's skills — that is how the system
tier keeps the tiers above it working and correct. A user agent cannot read a
system skill at all: the directory is not mounted into its namespace, so it is
absent rather than denied. Same enforcement as model grants.

`protected = true` in `skill.toml` takes a skill out of that entirely: only a
human commit changes it, whatever tier is asking. Used for skills whose failure
mode is "the machine cannot be repaired".

## Using a skill

An agent lists the skills it loads in `agent.toml`:

```toml
skills = ["shell-command"]
```

`make agent-check` rejects a skill the agent's tier cannot see, and one that
does not exist.

## Working with skills

```bash
make skills                              # tree, grouped by level
scripts/skillctl.py list --as app        # only what an app agent can see
scripts/skillctl.py can app system/manage-runner   # explain an access decision
scripts/skillctl.py new app my-skill     # scaffold
```

## What is here

| level | skill | for |
|---|---|---|
| user | `explain-error` | turning a failure into a next step |
| user | `format-output` | rendering a result for a real terminal |
| app | `shell-command` | intent into one POSIX command |
| app | `summarize` | a document into decisions, facts, open questions |
| app | `verify-command` | whether a command *answers*, not just runs |
| app | `distill-dataset` | training data verified by execution |
| system | `manage-runner` | the shared model runners |
| system | `train-model` | fine-tuning without repeating paid-for failures |
| system | `validate-model` | measuring a fine-tune honestly |
| system | `build-image` | building and booting the distribution |
| system | `recover` | a broken machine back to a shell (protected) |

The four newest carry what this repo learned the expensive way — an OOM at
step 344, a reward that scored two different answers identical, a GGUF that
loaded silently and emitted noise, a boot log sent to a screen nobody was
watching. A skill is the right place for that: an agent doing the same work
next month reads it before starting rather than rediscovering it.

## Writing one

`SKILL.md` is read by a model, so write it as a procedure, not as prose about a
procedure. Say what to do, in what order, and what to do when a step fails.
Keep it short — a skill that no longer fits in a glance has become two skills.
