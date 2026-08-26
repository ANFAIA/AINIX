# Agent entrypoint. Mojo first; drop to Python via interop where Mojo is thin.
#
# The shared base library (agents/lib) handles registration, the agent card,
# capability tokens, MCP tool calls and A2A task handling — an agent body
# should only contain its domain logic.
#
# Control flow is a pull loop, not a callback. A Mojo `def` cannot be passed to
# a Python function (it will not convert to PythonObject), so the agent asks
# for the next task rather than registering a handler. See docs/FINDINGS.md.

from std.python import Python


def main() raises:
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")

    # agent.model("gemma-3-1b") and agent.tool("<name>") exist only if
    # agent.toml granted them.
    var model = agent.model("gemma-3-1b")

    while True:
        # A task is a plain dict over the wire, so it is indexed, not attributed.
        var task = agent.next_task()      # blocks; None when shutting down
        if not task:
            break
        agent.reply(task, model.complete(task["input"]))
