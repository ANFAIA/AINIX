---
name: ainix-check
description: Run the AINIX regression suite — runner, manifests, capability enforcement, NixOS evaluation. Use before claiming a change works, after editing an agent manifest or skill, and when asked whether anything is broken.
---

Four checks. Run all four; report each result verbatim, including failures.

```bash
make smoke                # the runner answers a real completion
make agent-check          # every agent.toml is legal for its tier
./test/agent-policy.sh    # the capability system fails closed
make os-eval              # the NixOS configuration type-checks
```

`agent-policy.sh` is the one that matters most: it asserts that a user agent is
refused a model, a system skill, and an unlisted peer, and that an unregistered
connection is refused everything. Ten tests, and an unexpected ALLOW is worse
than an unexpected DENY.

If `make smoke` fails, check whether a runner is up (`docker ps`) and whether
weights exist (`ls ~/.cache/ainix/weights`) before anything else.

Never report "all good" without the four outputs. If one was skipped, say which.
