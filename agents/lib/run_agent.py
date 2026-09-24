"""Run one agent from its directory: register by name, then serve tasks.

This is the loop every generated main.mojo spells out — next_task, handle,
reply — for the image, where the Mojo toolchain is not packaged yet (it is not
in nixpkgs; see docs/FINDINGS.md). The agent's behaviour is the same either way:
handle() is the library default, and an agent that overrides it does so in its
own module next to agent.toml.

    python3 run_agent.py /etc/ainix/plane/agents/app/shell-expert
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

from ainix_agent import Agent, Denied


def main() -> int:
    here = Path(sys.argv[1]).resolve()
    os.chdir(here)

    # Registration can race the broker coming up; a unit that dies on the first
    # refused connect just gets restarted by systemd, but a short retry is kinder
    # to the journal.
    for attempt in range(10):
        try:
            agent = Agent.from_manifest("agent.toml")
            break
        except (ConnectionError, FileNotFoundError):
            time.sleep(min(5, 0.5 * (attempt + 1)))
    else:
        print("agentd never came up", file=sys.stderr)
        return 1

    # An agent may ship its own handler as handler.py:handle(agent, task).
    custom = here / "handler.py"
    handle = agent.handle
    if custom.exists():
        spec = importlib.util.spec_from_file_location("handler", custom)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        handle = lambda task: mod.handle(agent, task)   # noqa: E731

    print(f"{agent.name} serving", flush=True)
    while True:
        task = agent.next_task()
        if task is None:
            return 0
        try:
            out = handle(task)
        except Denied as e:
            out = {"error": f"refused: {e}"}
        except Exception as e:                       # an agent's bug is its reply
            out = {"error": f"{type(e).__name__}: {e}"}
        agent.reply(task, out)


if __name__ == "__main__":
    raise SystemExit(main())
