---
name: ainix-setup
description: Bring a fresh AINIX checkout to a working state — model runner answering on :8000, agent plane up, capability tests passing. Use when the repo has just been cloned, when nothing is running, or when the user asks to set up, install, or start AINIX.
---

Follow [agents_install.md](../../../agents_install.md) in order. Do not skip to
a later phase; each one checks the previous.

1. `docker info` — required, and the only hard dependency.
2. `make fetch MODEL_NAME=gemma-3-1b && make image && make run && make smoke`.
   `make smoke` must print PASS with a real sentence. Stop if it does not.
3. Start the broker and prove it fails closed:
   ```bash
   export AINIX_SOCK=/tmp/ainix-agentd.sock AINIX_ROOT=$PWD PYTHONPATH=$PWD/agents/lib
   python3 agents/system/agentd/agentd.py &
   ./test/agent-policy.sh
   ```
   All 10 must pass. A denial that turns into an allow is a stop-the-line bug.
4. Report what is running and what is not. Do not claim MAX works locally — it
   does not on macOS.
