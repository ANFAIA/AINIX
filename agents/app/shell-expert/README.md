# shell-expert agent

Backs `user/shell`. Converts intent into a command *plan*; it never runs
anything itself and holds no tool grants — the only capability it has is one
model endpoint.

It is also `user/shell`'s evolution parent: when it learns a new skill, it
registers the matching command on the shell's card.
