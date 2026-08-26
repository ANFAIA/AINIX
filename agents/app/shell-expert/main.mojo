# Holds the model grant that the shell agent deliberately does not have.
#
# Returns a plan, never an execution: {command, explain, mutates}. Deciding to
# run it belongs to the user agent, which shows it to a human first.

from std.python import Python

comptime SYSTEM = String(
    "Translate the request into one POSIX shell command. Answer as JSON: "
    "command, explain, mutates (bool). Set mutates=true for anything that "
    "writes, deletes, installs or sends. Never answer with prose."
)


def main() raises:
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")
    var model = agent.model("gemma-3-1b")

    while True:
        # A task is a plain dict over the wire, so it is indexed, not attributed.
        var task = agent.next_task()
        if not task:
            break
        # thinking=False matters: a reasoning model otherwise spends the whole
        # budget in reasoning_content and returns an empty contract.
        agent.reply(task, model.complete_json(
            system=SYSTEM, user=task["input"], thinking=False))
