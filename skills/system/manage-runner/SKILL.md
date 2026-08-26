# manage-runner

Model runners are shared: every agent granted a model talks to one of these.
Restarting one interrupts every agent that holds a grant to it.

## Procedure

1. Read `models.toml` for the runner's image, weights file, and device. Never
   infer a model name from a request — an agent asking for a model it was not
   granted must fail, not be served.
2. Before stopping a runner, list the agents holding grants to it and report
   them. A "quick restart" of a shared runner is not quick for them.
3. Start: the weights file must already exist locally. Do not download inside a
   start path — downloads belong to `firstboot` or an explicit fetch, where a
   human is watching the progress.
4. After start, poll `/health` before declaring the runner up. Reporting a
   runner ready while it is still loading weights produces failures that look
   like model errors.
5. Switching the default model rewrites `[model] default` in the state file and
   starts the new runner **before** stopping the old one, when memory allows.

## On failure

If a runner will not come up, capture the last 40 log lines and stop. Do not
restart in a loop — a crash-looping runner with a bad weights file will burn the
machine's memory and hide the original error.
