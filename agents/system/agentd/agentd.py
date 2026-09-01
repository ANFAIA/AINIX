"""agentd — the system agent the other agents depend on.

It is the only process that knows where anything is. Agents hold manifests;
agentd holds addresses, and hands out nothing a manifest did not ask for.

  registry    agents register a card; peers are discovered by skill, never by
              hardcoded address, so an agent can be replaced without editing
              the ones that call it.
  brokering   every task and every inference goes through here, which is what
              makes the manifest enforceable rather than advisory. An agent
              with no grant for a model cannot reach the endpoint at all —
              agentd holds the URL.
  skills      the level rule: a tier reads its own level and everything above
              it, never below.
  documents   classification: an agent reads a document only if its clearance
              is at or above the document's. Manifests declared clearance long
              before anything enforced it; a rule that only a validator checks
              is a comment with a test.
  tools       a tool is reachable only if the manifest granted it by name.
  audit       every allow and every deny, with a reason.

Deny is the default. Anything not explicitly granted is refused, and a refusal
is an answer — agents do not retry them.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import re
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("AINIX_ROOT", Path(__file__).resolve().parents[3]))
SOCK = os.environ.get("AINIX_SOCK", "/run/ainix/agentd.sock")
RUNNER = os.environ.get("AINIX_RUNNER", "http://127.0.0.1:8000")

# Top (least privileged) to bottom. A tier sees its own level and every level
# above it — the same ordering scripts/skillctl.py enforces.
LEVELS = ["user", "app", "system"]

# Document classification, lowest to highest. An agent reads at or below its own
# level. Loaded from groups.toml when a deployment has one; a deployment with no
# groups.toml simply has no classified documents.
CLEARANCE: list[str] = []
GROUPS: dict = {}

# Which tier may call which. A user agent asks app agents for work; app agents
# do not reach back up, and only system agents may call system agents.
MAY_CALL = {"user": {"app"}, "app": {"app"}, "system": {"user", "app", "system"}}


def now() -> float:
    return time.monotonic()


def load_groups() -> None:
    global CLEARANCE, GROUPS
    p = ROOT / "groups.toml"
    if not p.exists():
        return
    with p.open("rb") as fh:
        g = tomllib.load(fh)
    CLEARANCE = g.get("levels", {}).get("order", [])
    GROUPS = g.get("groups", {})


class Registry:
    def __init__(self):
        self.agents: dict[str, dict] = {}      # name -> {manifest, card, tier}
        self.inbox: dict[str, asyncio.Queue] = {}
        self.pending: dict[str, asyncio.Future] = {}
        self.seq = 0

    def add(self, name: str, manifest: dict) -> None:
        a = manifest["agent"]
        self.agents[name] = {"manifest": manifest, "tier": a["tier"],
                             "card": manifest.get("card", {})}
        self.inbox.setdefault(name, asyncio.Queue())

    def next_id(self) -> str:
        self.seq += 1
        return f"t{self.seq}"


REG = Registry()
AUDIT = []


def audit(who: str, op: str, target: str, allowed: bool, why: str = "") -> None:
    line = {"t": round(now(), 3), "who": who, "op": op, "target": target,
            "allow": allowed, "why": why}
    AUDIT.append(line)
    # journald in production; stderr is what a POC can actually be watched on.
    print(f"[audit] {'ALLOW' if allowed else 'DENY '} {who} {op} {target}"
          + (f" — {why}" if why else ""), file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# capability checks — each returns (ok, reason). The reason is the point: a
# rule nobody can predict is a rule nobody can design against.


def may_use_model(name: str, model: str) -> tuple[bool, str]:
    a = REG.agents.get(name)
    if not a:
        return False, "not registered"
    if model in a["manifest"]["agent"].get("models", []):
        return True, "granted by manifest"
    return False, f"{name} has no grant for {model!r}"


def may_task(caller: str, callee: str) -> tuple[bool, str]:
    a, b = REG.agents.get(caller), REG.agents.get(callee)
    if not a:
        return False, "caller not registered"
    if not b:
        return False, f"{callee} is not registered"
    if b["tier"] not in MAY_CALL[a["tier"]]:
        return False, f"a {a['tier']} agent may not call a {b['tier']} agent"
    if callee not in a["manifest"]["agent"].get("peers", []):
        return False, f"{caller} does not list {callee!r} as a peer"
    return True, "listed as a peer"


def may_read_skill(caller: str, level: str) -> tuple[bool, str]:
    a = REG.agents.get(caller)
    if not a:
        return False, "not registered"
    visible = LEVELS[: LEVELS.index(a["tier"]) + 1]
    if level in visible:
        return True, f"{a['tier']} sees {level}"
    return False, (f"{a['tier']} agents cannot see {level} skills — {level} is "
                   f"below {a['tier']}")


def clearance_of(name: str) -> str | None:
    a = REG.agents.get(name)
    return a["manifest"].get("documents", {}).get("clearance") if a else None


def may_read_document(caller: str, doc_level: str) -> tuple[bool, str]:
    """Read at or below your own clearance. Nothing about who is asking on
    whose behalf — a human cleared for everything does not lend that clearance
    to an agent by typing into it."""
    if not CLEARANCE:
        return True, "no classification in this deployment"
    mine = clearance_of(caller)
    if mine not in CLEARANCE:
        return False, f"{caller} holds no clearance"
    if doc_level not in CLEARANCE:
        return False, f"unknown classification {doc_level!r}"
    if CLEARANCE.index(doc_level) <= CLEARANCE.index(mine):
        return True, f"{mine} covers {doc_level}"
    return False, (f"{caller} holds {mine}; this document is {doc_level}")


def may_use_tool(caller: str, tool: str) -> tuple[bool, str]:
    a = REG.agents.get(caller)
    if not a:
        return False, "not registered"
    if tool in a["manifest"]["agent"].get("tools", []):
        return True, "granted by manifest"
    return False, f"{caller} has no grant for tool {tool!r}"


def documents() -> dict:
    """The store, as {id: {classification, title, body}}. A directory of files
    with a classification line, so a deployment can keep them in git and a
    human can read them without a tool."""
    out = {}
    d = ROOT / "documents"
    for p in sorted(d.glob("*.md")) if d.exists() else []:
        text = p.read_text()
        m = re.search(r"^classification:\s*(\w+)", text, re.M)
        out[p.stem] = {"classification": m.group(1) if m else "public",
                       "title": p.stem.replace("-", " "),
                       "body": text}
    return out


def find_skill(name: str) -> tuple[str, Path] | tuple[None, None]:
    for lvl in LEVELS:
        p = ROOT / "skills" / lvl / name / "SKILL.md"
        if p.exists():
            return lvl, p
    return None, None


# --------------------------------------------------------------------------
# the model plane — agents never see this URL


LOADED = {"name": None}


def loaded_model() -> str | None:
    """What the runner actually has open. There is one runner in v1, so a
    grant for `gemma-3-1b` served by a runner holding Qwen would silently
    answer from the wrong model — the grant is policy, the loaded weights are
    fact, and the audit line has to show both."""
    try:
        with urllib.request.urlopen(f"{RUNNER}/v1/models", timeout=5) as r:
            m = json.load(r)["models"][0]
        return Path(m.get("name", "")).name or None
    except Exception:
        return None


def infer(model: str, messages: list, thinking: bool = False,
          max_tokens: int = 512) -> str:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": bool(thinking)}}
    req = urllib.request.Request(f"{RUNNER}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    return d["choices"][0]["message"].get("content") or ""


# --------------------------------------------------------------------------


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    me = None                       # set by register; identity is per-connection
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                await send(writer, ok=False, error="malformed JSON")
                continue
            me = await dispatch(msg, me, writer)
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def send(w: asyncio.StreamWriter, **kw) -> None:
    w.write((json.dumps(kw) + "\n").encode())
    await w.drain()


async def dispatch(msg: dict, me: str | None, w: asyncio.StreamWriter):
    op = msg.get("op")

    if op == "register":
        m = msg["manifest"]
        a = m["agent"]
        me = f"{a['tier']}/{a['name']}"
        REG.add(me, m)
        audit(me, "register", me, True, f"tier={a['tier']}")
        await send(w, ok=True, name=me)
        return me

    if me is None:
        await send(w, ok=False, error="register first")
        return me

    if op == "discover":
        skill = msg.get("skill", "")
        cards = [{"name": n, "tier": v["tier"], **v["card"]}
                 for n, v in REG.agents.items()
                 if skill in v["card"].get("skills", [])
                 and may_task(me, n)[0]]
        audit(me, "discover", skill, True, f"{len(cards)} match")
        await send(w, ok=True, cards=cards)

    elif op == "infer":
        ok, why = may_use_model(me, msg["model"])
        served = LOADED["name"] or loaded_model()
        LOADED["name"] = served
        if ok and served and msg["model"].split("-")[0] not in served.lower():
            why += f" — WARNING: runner is serving {served}, not {msg['model']}"
        audit(me, "infer", msg["model"], ok, why)
        if not ok:
            await send(w, ok=False, error=why)
        else:
            content = await asyncio.to_thread(
                infer, msg["model"], msg["messages"],
                msg.get("thinking", False), msg.get("max_tokens", 512))
            await send(w, ok=True, content=content)

    elif op == "task":
        callee = msg["to"]
        ok, why = may_task(me, callee)
        audit(me, "task", callee, ok, why)
        if not ok:
            await send(w, ok=False, error=why)
        else:
            tid = REG.next_id()
            fut = asyncio.get_running_loop().create_future()
            REG.pending[tid] = fut
            await REG.inbox[callee].put(
                {"id": tid, "from": me, "skill": msg.get("skill", ""),
                 "input": msg.get("input")})
            try:
                out = await asyncio.wait_for(fut, timeout=msg.get("timeout", 300))
                await send(w, ok=True, output=out)
            except asyncio.TimeoutError:
                REG.pending.pop(tid, None)
                await send(w, ok=False, error=f"{callee} did not answer in time")

    elif op == "next_task":
        task = await REG.inbox[me].get()
        await send(w, ok=True, task=task)

    elif op == "reply":
        fut = REG.pending.pop(msg["task_id"], None)
        if fut and not fut.done():
            fut.set_result(msg.get("output"))
        await send(w, ok=True)

    elif op == "skill":
        level, path = find_skill(msg["name"])
        if level is None:
            audit(me, "skill", msg["name"], False, "no such skill")
            await send(w, ok=False, error=f"no such skill: {msg['name']}")
        else:
            ok, why = may_read_skill(me, level)
            audit(me, "skill", f"{level}/{msg['name']}", ok, why)
            await send(w, ok=ok, text=path.read_text() if ok else "",
                       error=None if ok else why)

    elif op == "document":
        docs = documents()
        doc = docs.get(msg.get("id", ""))
        if doc is None:
            audit(me, "document", msg.get("id", ""), False, "no such document")
            await send(w, ok=False, error=f"no such document: {msg.get('id')!r}")
        else:
            ok, why = may_read_document(me, doc["classification"])
            audit(me, "document", f"{msg['id']}[{doc['classification']}]", ok, why)
            await send(w, ok=ok, document=doc if ok else None,
                       error=None if ok else why)

    elif op == "documents":
        # A listing shows only what the caller could open. Titles leak: a
        # confidential document called "acquisition-of-globex" is a disclosure
        # even when the body stays shut.
        visible = {i: {"classification": d["classification"], "title": d["title"]}
                   for i, d in documents().items()
                   if may_read_document(me, d["classification"])[0]}
        audit(me, "documents", "list", True, f"{len(visible)} visible")
        await send(w, ok=True, documents=visible)

    elif op == "tool":
        ok, why = may_use_tool(me, msg.get("name", ""))
        audit(me, "tool", msg.get("name", ""), ok, why)
        await send(w, ok=ok, error=None if ok else why)

    elif op == "status":
        await send(w, ok=True, agents={n: v["tier"] for n, v in REG.agents.items()},
                   audit=AUDIT[-20:])

    else:
        await send(w, ok=False, error=f"unknown op {op!r}")

    return me


async def main() -> int:
    path = Path(SOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    load_groups()
    server = await asyncio.start_unix_server(handle, str(path))
    os.chmod(path, 0o660)
    print(f"agentd listening on {path} | runner {RUNNER}"
          + (f" | clearance {'<'.join(CLEARANCE)}" if CLEARANCE else ""),
          file=sys.stderr, flush=True)
    async with server:
        await server.serve_forever()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
