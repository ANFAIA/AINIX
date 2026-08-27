# What a person at ACME actually types into.
#
# It discovers by capability rather than by name: "who can assess an article"
# is a question for the registry, so an agent can be replaced without editing
# the console.

from std.python import Python


def main() raises:
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")

    while True:
        var line = agent.readline(agent.prompt())
        if not line:
            break
        var cards = agent.discover(agent.route(line))
        if not cards:
            print("nobody here can do that")
            continue
        var answer = agent.peer(cards[0]["name"]).task("do", line)
        print(agent.render(answer))
