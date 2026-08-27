# draft public help centre articles for a human to approve and publish

from std.python import Python


def main() raises:
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")

    while True:
        var task = agent.next_task()
        if not task:
            break
        agent.reply(task, agent.handle(task))
