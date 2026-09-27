"""End-to-end on the image: the console asks shell-expert, which asks the model.

Run as ainix-user-shell. Proves the whole path in one call — the console's
identity, the peer grant, the expert's model grant, agentd reaching the runner —
because every hop that fails raises Denied or returns an error dict. The test
model is a 19 MB story model, so the answer is not a shell command; what is
checked is that the model was reached and answered, not what it said.
"""
import sys

from ainix_agent import Agent

shell = Agent.from_manifest(sys.argv[1] + "/agents/user/shell/agent.toml")
# Through the OS's decision layer, not straight to a named peer: the console
# says what it wants, Laya decides who answers, agentd enforces the choice.
r = shell.ask("list files", timeout=120)
decision = r["decision"]
if r["routed_to"] != "app/shell-expert" or "laya not running" in str(decision.get("source")):
    raise SystemExit(f"not routed by laya: {r['routed_to']} {decision}")
print("routed by laya:", decision.get("source"), decision.get("engine"))
out = r["output"]
if not isinstance(out, dict):
    raise SystemExit(f"unexpected reply: {out!r}")
if "raw" in out or "command" in out:        # the model answered, JSON or not
    print("model answered through agentd:", str(out)[:80])
    raise SystemExit(0)
raise SystemExit(f"no model answer in the reply: {out}")
