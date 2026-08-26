# shell — the interface *is* an agent

On AINIX the login shell is a user agent, not a special case. It is the smallest
possible human interface and it obeys the same rules as every other agent: its
own uid, its own cgroup, no model access, and only the peers its manifest lists.

## How it behaves

- Input that parses as a command runs as a command. `ls`, `cat`, pipes,
  redirection — unchanged. The shell agent execs a plain POSIX shell for this,
  it does not reimplement one.
- Input the parser rejects is treated as intent and handed to `app/shell-expert`
  as an A2A task. That agent — not the shell — holds the model grant.
- A proposed action that mutates state is shown and confirmed before it runs.
  The shell agent has no capability to run anything the user has not seen.

## Why it is not simply "an LLM in a prompt"

The shell holds **no** model grant. Compromising it yields a shell, which the
user already had — not model access, not tool access, not another agent's
capabilities. That separation is the point, and it is enforced by the netns and
socket mounts, not by prompt instructions.

## Escape hatch

`/bin/sh` remains on the image and remains a valid login shell. A system whose
only interface is an agent is a system you cannot repair when the agent is the
thing that broke.
