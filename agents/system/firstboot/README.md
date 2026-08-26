# firstboot — what the machine asks on its first start

Runs once, on the console, before the login shell. Two questions, in this
order, and the order is the whole design:

1. **Network first.** Every later question depends on it. If there is none, the
   agent says so plainly, offers whatever configuration tools are actually on
   the image (`nmtui`, `nmcli`, `iwctl` — only the ones present are listed),
   and lets the user continue offline rather than trapping them in a wizard.
2. **Then the model.** It states the default — name, size, what it is for — and
   offers the full catalog. Nothing downloads without a choice.

## The catalog view

Grouped by what the machine can actually run, not by vendor:

```
  small — runs on CPU, on anything
     1. gemma-3-1b          769MB  ...  [default, downloaded]
     2. granite-4.2-3b       ~2GB  ...
  mid — small GPU, or a patient CPU
     5. qwen3-8b             ~5GB  ...
  large — real GPU territory
     9. qwen3-30b-a3b       ~18GB  ...
  remote — third-party APIs, off until you add a key
```

Each entry is tagged with the truth about *this* machine: `downloaded`,
`needs network`, or `too big for this machine` (RAM is read from the host and
compared against the weight size plus headroom). A user should not be able to
pick something that cannot run.

Remote models are listed but never selectable here — enabling one means putting
a key in `agentd`'s environment, which is a deliberate act, not a first-boot
checkbox.

## Offline is a supported outcome, not a failure

With no network and no weights, setup records the choice and drops to a shell.
The machine is still usable; `ainix-firstboot` re-runs when connected. A
distribution that is unusable without a download is a worse distribution.

## State

Written to `/var/lib/ainix/state.toml` (or `~/.local/state/ainix/` when not
root). Delete it, or run `ainix-firstboot --force`, to choose again.

## Try it

```bash
make firstboot                     # real run
make firstboot ARGS=--force        # choose again
AINIX_PROBE_HOST=nonexistent.invalid make firstboot ARGS=--force   # offline path
```

## Wiring on the real image

A `systemd` unit ordered `Before=getty@tty1.service`, `ConditionPathExists=!`
on the state file, with `StandardInput=tty`. It is a system agent, so it is
`evolution.mode = "frozen"` — the thing that runs before everything else is not
something an agent gets to rewrite.
