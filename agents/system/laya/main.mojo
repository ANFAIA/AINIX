# Laya — the decision layer. Mojo owns the loop; the decision's deterministic
# half is the compiled laya_core module, the model call goes through agentd.

from std.python import Python


def main() raises:
    Python.add_to_path(".")
    var laya = Python.import_module("handler")
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")

    while True:
        var task = agent.next_task()
        if not task:
            break
        agent.reply(task, laya.handle(agent, task))
