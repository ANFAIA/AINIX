# Drafts what ACME says in public.
#
# Publishing is not in this agent's hands: it returns a draft and a proposed
# time, and the tool that posts is gated on a human approving it. An agent that
# can publish without review is a brand incident waiting for a bad sample.

from std.python import Python


def main() raises:
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")
    var model = agent.model("qwen3.5-2b")
    var voice = agent.skill("brand-voice")

    while True:
        var task = agent.next_task()
        if not task:
            break
        agent.reply(task, model.complete_json(
            system=voice, user=task["input"], thinking=False))
