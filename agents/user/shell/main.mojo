# The login shell, as an agent.
#
# Design rule: parse first, ask second. Anything that is a valid command is
# executed as one — no model in the path, no latency, no surprises. Only what
# the parser rejects becomes intent, and intent goes to the operating system's
# decision layer: `ask` hands it to Laya, which picks the agent that answers
# from the ones this shell may use. The shell does not name an expert; the OS
# decides.

from std.python import Python


def main() raises:
    var ainix = Python.import_module("ainix_agent")

    var agent = ainix.Agent.from_manifest("agent.toml")
    var sh = ainix.Shell("/bin/sh")              # real shell; we do not reimplement one

    while True:
        var line = agent.readline(agent.prompt())
        if not line:
            break

        if sh.parses(line):
            _ = sh.run(line)
            continue

        # Not a command — intent. Laya decides who answers; agentd enforces it.
        var r = agent.ask(line)
        var plan = r["output"]
        print(agent.render(plan), "   [", r["routed_to"], "via laya:",
              r["decision"]["source"], "]")
        # A plan is a dict over the wire: indexed, never attributed. The
        # previous version read plan.mutates and plan.explain(), which a dict
        # does not have — this path had never run.
        if not plan.get("command"):
            continue
        if plan.get("mutates", True) and not agent.confirm(String(plan.get("explain", ""))):
            continue
        _ = sh.run(plan["command"])
