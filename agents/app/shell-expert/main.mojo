# Holds the model grant that the shell agent deliberately does not have.
#
# Returns a plan, never an execution: {command, explain, mutates}. Deciding to
# run it belongs to the user agent, which shows it to a human first.

from python import Python


def main():
    ainix = Python.import_module("ainix_agent")
    agent = ainix.Agent.from_manifest("agent.toml")
    model = agent.model("gemma-3-1b")

    @parameter
    fn handle(task: PythonObject) -> PythonObject:
        return model.complete_json(
            system="Translate the request into one POSIX shell command. "
                   "Answer as JSON: command, explain, mutates (bool). "
                   "Set mutates=true for anything that writes, deletes, installs "
                   "or sends. Never answer with prose.",
            user=task.input,
        )

    agent.serve(handle)
