"""On-image self-check: is the broker up, and does it still refuse?

Registers as the login shell — a real agent in the tree, since invented names
are refused — and checks one allow and three denials. A probe that only
confirms the happy path would have passed happily while the broker accepted
forged manifests.
"""
import json
import os
import socket

SOCK = os.environ.get("AINIX_SOCK", "/run/ainix/agentd.sock")
s = socket.socket(socket.AF_UNIX)
s.connect(SOCK)
f = s.makefile("rwb")


def call(**kw):
    f.write((json.dumps(kw) + "\n").encode())
    f.flush()
    return json.loads(f.readline())


checks = [
    ("register as user/shell",         call(op="register", name="user/shell")["ok"], True),
    ("own-level skill",                call(op="skill", name="explain-error")["ok"], True),
    ("system skill refused",           call(op="skill", name="manage-runner")["ok"], False),
    ("model refused to a user agent",  call(op="infer", model="gemma-3-1b", messages=[])["ok"], False),
    ("status refused below system",    call(op="status")["ok"], False),
]
bad = 0
for name, got, want in checks:
    ok = got == want
    bad += not ok
    print(f"PROBE {'ok  ' if ok else 'FAIL'} {name}")
print(f"PROBE {len(checks) - bad}/{len(checks)}")
raise SystemExit(1 if bad else 0)
