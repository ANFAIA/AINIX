# Reads the open internet so that other agents do not have to.
#
# Deliberately the least privileged agent at ACME: it touches untrusted pages
# all day, so it holds public clearance and no write tools. Anything it finds
# travels as data to an agent that can act on it.

from std.python import Python


def main() raises:
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")
    var model = agent.model("gemma-3-1b")
    var search = agent.tool("web-search")

    while True:
        var task = agent.next_task()
        if not task:
            break
        var hits = search.run(task["input"])
        agent.reply(task, model.complete_json(
            system=agent.skill("assess-article"), user=hits, thinking=False))
