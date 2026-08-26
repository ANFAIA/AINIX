"""ainix-agent — what every agent links against.

An agent never opens a model socket, never resolves a peer's address, and never
reads another tier's skills. It asks agentd, and agentd answers according to the
manifest the agent was built with. That is the whole design: the manifest is
evaluated at build time, and agentd is the only thing holding the addresses.

Wire format is newline-delimited JSON over a Unix socket. Small, greppable, and
debuggable with `socat` — an audit trail nobody can read is not one.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tomllib
from pathlib import Path

SOCK = os.environ.get("AINIX_SOCK", "/run/ainix/agentd.sock")


class Denied(Exception):
    """agentd refused. Never retried, never worked around — a denial is an
    answer, not a transient failure."""


class Conn:
    """One line-delimited JSON connection to agentd."""

    def __init__(self, path: str = SOCK):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.f = self.sock.makefile("rwb")

    def call(self, op: str, sock_timeout: float | None = None, **kw) -> dict:
        """`sock_timeout` is how long to wait on the wire. Anything named
        `timeout` inside kw is a *task* deadline for agentd to enforce — the
        two are different clocks and conflating them makes a slow peer look
        like a broken socket."""
        self.sock.settimeout(sock_timeout)
        self.f.write((json.dumps({"op": op, **kw}) + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise ConnectionError("agentd closed the connection")
        r = json.loads(line)
        if not r.get("ok"):
            raise Denied(r.get("error", "denied"))
        return r

    def close(self) -> None:
        self.f.close()
        self.sock.close()


class Model:
    """A model the manifest granted. There is no constructor an agent can use
    to reach one it was not granted — the endpoint lives in agentd."""

    def __init__(self, conn: Conn, name: str):
        self._conn, self.name = conn, name

    def complete(self, prompt: str, system: str = "", **kw) -> str:
        msgs = ([{"role": "system", "content": system}] if system else [])
        msgs.append({"role": "user", "content": str(prompt)})
        r = self._conn.call("infer", model=self.name, messages=msgs,
                            sock_timeout=300, **kw)
        return r["content"]

    def complete_json(self, system: str, user: str, thinking: bool = False,
                      **kw) -> dict:
        """Reasoning models spend the whole budget in reasoning_content and
        return an empty string unless thinking is turned off. An agent that
        wants an answer has to ask for one."""
        raw = self.complete(user, system=system, thinking=thinking, **kw)
        try:
            start, end = raw.find("{"), raw.rfind("}")
            return json.loads(raw[start:end + 1])
        except (ValueError, json.JSONDecodeError):
            return {"error": "model did not return JSON", "raw": raw[:400]}


class Peer:
    """Another agent, reached by A2A task. Present only if the manifest listed
    it: agentd checks the caller's peers on every task."""

    def __init__(self, conn: Conn, name: str):
        self._conn, self.name = conn, name

    def task(self, skill: str, payload, timeout: float = 300):
        # agentd answers with an error when the deadline passes, so the wire
        # wait is deliberately longer — we want its reason, not a socket error.
        r = self._conn.call("task", to=self.name, skill=skill, input=payload,
                            timeout=timeout, sock_timeout=timeout + 10)
        return r["output"]


class Agent:
    def __init__(self, manifest: dict, conn: Conn):
        self.manifest, self._conn = manifest, conn
        a = manifest["agent"]
        self.name = f"{a['tier']}/{a['name']}"
        self.tier = a["tier"]

    @classmethod
    def from_manifest(cls, path: str = "agent.toml") -> "Agent":
        with open(path, "rb") as fh:
            m = tomllib.load(fh)
        conn = Conn()
        conn.call("register", manifest=m)
        return cls(m, conn)

    # --- capabilities -----------------------------------------------------
    def model(self, name: str) -> Model:
        if name not in self.manifest["agent"].get("models", []):
            raise Denied(f"{self.name} has no grant for model {name!r}")
        return Model(self._conn, name)

    def peer(self, name: str) -> Peer:
        if name not in self.manifest["agent"].get("peers", []):
            raise Denied(f"{self.name} does not list {name!r} as a peer")
        return Peer(self._conn, name)

    def discover(self, skill: str) -> list[dict]:
        """Find agents by what they can do, not by where they live."""
        return self._conn.call("discover", skill=skill)["cards"]

    def skill(self, name: str) -> str:
        """Read a skill's SKILL.md. agentd enforces the level rule: own level
        and everything above it, never below."""
        return self._conn.call("skill", name=name)["text"]

    # --- serving ----------------------------------------------------------
    def next_task(self, timeout: float | None = None):
        """Blocks until a task arrives. A pull loop, not a callback — a Mojo
        `def` cannot be handed to Python, so the agent owns its control flow."""
        try:
            r = self._conn.call("next_task", sock_timeout=timeout)
        except (ConnectionError, socket.timeout):
            return None
        return r.get("task")

    def reply(self, task, output) -> None:
        self._conn.call("reply", task_id=task["id"], output=output)

    # --- console helpers used by user agents ------------------------------
    def prompt(self) -> str:
        return f"{self.name.split('/')[-1]}> "

    def readline(self, prompt: str) -> str:
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""

    def confirm(self, what: str) -> bool:
        return self.readline(f"  {what}\n  run it? [y/N]: ").lower().startswith("y")


class Shell:
    """A real shell. We do not reimplement one — parsing is `sh -n`, running is
    `sh -c`, and both are the same binary the user already trusts."""

    def __init__(self, path: str = "/bin/sh"):
        self.path = path

    def parses(self, line: str) -> bool:
        import subprocess
        return subprocess.run([self.path, "-n", "-c", line],
                              capture_output=True).returncode == 0

    def run(self, line: str) -> int:
        import subprocess
        return subprocess.run([self.path, "-c", line]).returncode
