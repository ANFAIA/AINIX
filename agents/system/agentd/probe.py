import json, socket
s = socket.socket(socket.AF_UNIX); s.connect("/run/ainix/agentd.sock")
f = s.makefile("rwb")
def call(**kw):
    f.write((json.dumps(kw) + "\n").encode()); f.flush()
    return json.loads(f.readline())
print("REGISTER:", call(op="register", manifest={"agent": {"name": "probe", "tier": "system"}}))
print("SKILL:", call(op="skill", name="manage-runner")["ok"])
print("AGENTS:", list(call(op="status")["agents"]))
