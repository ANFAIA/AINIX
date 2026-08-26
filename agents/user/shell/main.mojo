# The login shell, as an agent.
#
# Design rule: parse first, ask second. Anything that is a valid command is
# executed as one — no model in the path, no latency, no surprises. Only what
# the parser rejects becomes a question for app/shell-expert.

from python import Python


def main():
    ainix = Python.import_module("ainix_agent")
    os = Python.import_module("os")

    agent = ainix.Agent.from_manifest("agent.toml")
    expert = agent.peer("app/shell-expert")   # present only because peers listed it
    sh = ainix.Shell("/bin/sh")               # real shell; we do not reimplement one

    while True:
        line = agent.readline(agent.prompt())
        if not line:
            break

        if sh.parses(line):
            sh.run(line)
            continue

        # Not a command — intent. The expert holds the model grant, not us.
        plan = expert.task("shell.ask", line)
        if plan.mutates and not agent.confirm(plan.explain()):
            continue
        sh.run(plan.command)
