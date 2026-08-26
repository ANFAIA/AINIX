# Agent entrypoint. Mojo first; drop to Python via interop where Mojo is thin.
#
# The shared base library (agents/lib) handles registration, the agent card,
# capability tokens, MCP tool calls and A2A task handling — an agent body
# should only contain its domain logic.

from python import Python


def main():
    ainix = Python.import_module("ainix_agent")
    agent = ainix.Agent.from_manifest("agent.toml")

    @parameter
    fn handle(task: PythonObject) -> PythonObject:
        # `task.input` is the A2A task payload.
        # agent.model("gemma-3-1b") and agent.tool("<name>") are only present
        # if agent.toml granted them.
        return agent.model("gemma-3-1b").complete(task.input)

    agent.serve(handle)
