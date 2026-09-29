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

  identity    an agent says only its NAME. Its manifest is read from the agent
              tree on disk — never taken from the caller, or every grant in the
              system would be whatever the caller claimed. With
              AINIX_IDENTITY=uid the name is also bound to the connecting
              process's uid (SO_PEERCRED / LOCAL_PEERCRED), so an agent cannot
              claim to be another one either.

Deny is the default. Anything not explicitly granted is refused, and a refusal
is an answer — agents do not retry them.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import pwd
import re
import socket
import struct
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import policy  # noqa: E402  — the decisions: Mojo when built, Python twin otherwise

ROOT = Path(os.environ.get("AINIX_ROOT", Path(__file__).resolve().parents[3]))
SOCK = os.environ.get("AINIX_SOCK", "/run/ainix/agentd.sock")
RUNNER = os.environ.get("AINIX_RUNNER", "http://127.0.0.1:8000")

# More than one runner: {"qwen3-8b": "http://127.0.0.1:8001", ...}. A model not
# listed goes to RUNNER. This is what lets Laya's small model and the model it
# escalates to be served side by side.
RUNNERS: dict[str, str] = json.loads(os.environ.get("AINIX_RUNNERS", "{}") or "{}")

# Where classified documents live. NOT under ROOT on the image: ROOT is a Nix
# store path, and the Nix store is readable by every process on the machine —
# a document placed there is readable by any agent without asking agentd,
# whatever its classification. The image points this at a 0700 directory
# owned by the broker.
DOCUMENTS = Path(os.environ.get("AINIX_DOCUMENTS", ROOT / "documents"))

# "uid": a name is accepted only from the uid of the system user
#        ainix-<tier>-<name>, which is how the image runs each agent.
# "name": the manifest still comes from disk, but any local process in the
#        broker's group may claim any name. Development only, and every
#        registration says so in the audit log.
IDENTITY = os.environ.get("AINIX_IDENTITY", "name")

# Ceilings on what a caller may ask for. A grant to a model is a grant to use
# it, not to monopolise it: one agent asking for a million tokens, or parking a
# task for a day, holds the shared runner and the broker for everyone else.
MAX_TOKENS = int(os.environ.get("AINIX_MAX_TOKENS", "4096"))
MAX_TASK_SECONDS = float(os.environ.get("AINIX_MAX_TASK_SECONDS", "900"))
MAX_LINE = 1 << 20          # one request, one line, at most 1 MiB

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
# Which tier may call which lives in agents/lib/ainix_policy.mojo.


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
    """Live agents only. An agent is in here while its connection is open and
    not a moment longer — a registration that outlives its process is a queue
    that swallows tasks until they time out."""

    def __init__(self):
        self.agents: dict[str, dict] = {}      # name -> {manifest, tier, card}
        self.inbox: dict[str, asyncio.Queue] = {}
        self.pending: dict[str, tuple[asyncio.Future, str]] = {}  # tid -> (fut, callee)
        self.seq = 0

    def add(self, name: str, manifest: dict) -> None:
        a = manifest["agent"]
        self.agents[name] = {"manifest": manifest, "tier": a["tier"],
                             "card": manifest.get("card", {})}
        self.inbox[name] = asyncio.Queue()

    def remove(self, name: str) -> None:
        self.agents.pop(name, None)
        self.inbox.pop(name, None)
        # Anyone waiting on this agent gets an answer now instead of a timeout.
        for tid, (fut, callee) in list(self.pending.items()):
            if callee == name and not fut.done():
                fut.set_exception(ConnectionError(f"{name} went away"))
                self.pending.pop(tid, None)

    def next_id(self) -> str:
        self.seq += 1
        return f"t{self.seq}"


_MANIFESTS: dict[str, dict | None] = {}


def load_manifest(name: str) -> dict | None:
    """The authoritative manifest for `tier/name`, read from the agent tree.

    This is the whole capability system in one function: whatever a caller
    sends, the grants that apply are the ones on disk, which Nix built and a
    human reviewed."""
    if name in _MANIFESTS:
        return _MANIFESTS[name]
    parts = name.split("/")
    m = None
    if (len(parts) == 2 and parts[0] in LEVELS
            and policy.valid_name(parts[1])):
        p = ROOT / "agents" / parts[0] / parts[1] / "agent.toml"
        if p.exists():
            with p.open("rb") as fh:
                m = tomllib.load(fh)
            a = m.get("agent", {})
            if a.get("tier") != parts[0] or a.get("name") != parts[1]:
                m = None           # a manifest that disagrees with its path
    _MANIFESTS[name] = m
    return m


def peer_uid(sock: socket.socket | None) -> int | None:
    """The uid of the process on the other end of a Unix socket, from the
    kernel rather than from anything the process said."""
    if sock is None:
        return None
    try:
        if sys.platform.startswith("linux"):
            raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                  struct.calcsize("3i"))
            return struct.unpack("3i", raw)[1]
        if sys.platform == "darwin":
            # SOL_LOCAL = 0, LOCAL_PEERCRED = 1 -> struct xucred
            raw = sock.getsockopt(0, 1, 76)
            return struct.unpack_from("I", raw, 4)[0]
    except OSError:
        return None
    return None


def expected_uid(name: str) -> int | None:
    try:
        return pwd.getpwnam("ainix-" + name.replace("/", "-")).pw_uid
    except KeyError:
        return None


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
    """Policy first, liveness last. Whether an agent is running is itself
    information, and a caller with no right to reach it should learn the rule
    that stops it — not whether the target happens to be up."""
    a = REG.agents.get(caller)
    if not a:
        return False, "caller not registered"
    target = load_manifest(callee)
    if target is None:
        return False, f"{callee} does not exist"
    callee_tier = target["agent"]["tier"]
    if not policy.tier_may_call(a["tier"], callee_tier):
        return False, f"a {a['tier']} agent may not call a {callee_tier} agent"
    if callee not in a["manifest"]["agent"].get("peers", []):
        return False, f"{caller} does not list {callee!r} as a peer"
    if callee not in REG.agents:
        return False, f"{callee} is not running"
    return True, "listed as a peer"


def may_read_skill(caller: str, level: str) -> tuple[bool, str]:
    a = REG.agents.get(caller)
    if not a:
        return False, "not registered"
    if policy.tier_sees_level(a["tier"], level):
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
    if policy.clearance_covers(mine, doc_level, CLEARANCE):
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
    d = DOCUMENTS
    # Fail closed: a document with no classification line — or one that names
    # a level this deployment does not have — is treated as the highest level.
    # It used to default to "public", so forgetting one line published it.
    for p in sorted(d.glob("*.md")) if d.exists() else []:
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^classification:\s*(\w+)", text, re.M)
        level = policy.classify(m.group(1) if m else None, CLEARANCE)
        out[p.stem] = {"classification": level,
                       "title": p.stem.replace("-", " "),
                       "body": text}
    return out




def find_skill(name: str) -> tuple[str, Path] | tuple[None, None]:
    """Locate a skill by name, at whichever level holds it.

    The name is validated before it touches a path. It used to be pasted into
    one as-is, so a user agent asking for "../system/recover" was found under
    skills/user/ — the level rule said allow, and the audit log recorded
    "user sees user" for a read of a protected system skill."""
    if not policy.valid_name(name or ""):
        return None, None
    base = (ROOT / "skills").resolve()
    for lvl in LEVELS:
        p = (ROOT / "skills" / lvl / name / "SKILL.md").resolve()
        if p.is_file() and p.is_relative_to(base / lvl):
            return lvl, p
    return None, None


# --------------------------------------------------------------------------
# the model plane — agents never see this URL




_SERVED: dict[str, str | None] = {}


def loaded_model(model: str | None = None) -> str | None:
    """What the runner for `model` actually has open. A grant for `gemma-3-1b`
    served by a runner holding Qwen would silently answer from the wrong model —
    the grant is policy, the loaded weights are fact. Returned with every
    inference so a caller can tell (Laya uses it to refuse a fake escalation:
    two model names routed to the same runner are one model)."""
    url = RUNNERS.get(model, RUNNER) if model else RUNNER
    if _SERVED.get(url):
        return _SERVED[url]
    try:
        with urllib.request.urlopen(f"{url}/v1/models", timeout=5) as r:
            m = json.load(r)["models"][0]
        _SERVED[url] = Path(m.get("name") or m.get("model") or "").name or None
        return _SERVED[url]
    except Exception:
        return None


def infer(model: str, messages: list, thinking: bool = False,
          max_tokens: int = 512, temperature: float | None = None,
          response_format: dict | None = None, logprobs: int = 0) -> dict:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": bool(thinking)}}
    if temperature is not None:
        body["temperature"] = float(policy.clamp(float(temperature), 0.0, 2.0))
    # Constrained decoding: the runner generates only text matching the schema.
    # Laya relies on it to make the small model choose from a list rather than
    # invent a name.
    if isinstance(response_format, dict):
        body["response_format"] = response_format
    if logprobs:
        body["logprobs"] = True
        body["top_logprobs"] = int(policy.clamp(int(logprobs), 1, 20))
    req = urllib.request.Request(f"{RUNNERS.get(model, RUNNER)}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        # The runner says why — context overflow, model still loading — and
        # "HTTPError" alone sent the reader into a VM to find out.
        try:
            why = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            why = ""
        raise RuntimeError(f"runner answered {e.code}: {why or e.reason}") from None
    c = d["choices"][0]
    return {"content": c["message"].get("content") or "",
            "logprobs": (c.get("logprobs") or {}).get("content") if logprobs else None}


# --------------------------------------------------------------------------


LAYA = "system/laya"


async def dispatch_task(sender: str, callee: str, skill: str, payload,
                        timeout: float):
    """Queue a task for `callee` from `sender` and wait for its answer."""
    tid = REG.next_id()
    fut = asyncio.get_running_loop().create_future()
    REG.pending[tid] = (fut, callee)
    await REG.inbox[callee].put({"id": tid, "from": sender, "skill": skill,
                                 "input": payload})
    try:
        return await asyncio.wait_for(
            fut, timeout=float(policy.clamp(timeout, 1.0, MAX_TASK_SECONDS)))
    finally:
        REG.pending.pop(tid, None)


async def laya_decide(caller: str, request: str, cands: list[dict]) -> dict:
    """Ask Laya. If Laya is not running, decide with its model-free half
    directly — routing degrades to keywords, it does not stop."""
    if LAYA in REG.agents:
        try:
            d = await dispatch_task(caller, LAYA, "laya.decide",
                                    {"request": request, "candidates": cands}, 30)
            if isinstance(d, dict):
                return d
        except (asyncio.TimeoutError, ConnectionError):
            pass
    from laya_route import core, keyword_pick
    best, score = keyword_pick(request, cands)
    only = cands[0]["name"] if len(cands) == 1 else None
    pick, source = core.decide(None, 0, best, score, 1.0, only)
    skill = next((c["skills"][0] for c in cands if c["name"] == pick and c["skills"]), None)
    return {"agent": pick, "skill": skill, "source": f"{source} (laya not running)",
            "keyword_pick": best, "keyword_score": score, "engine": str(core.engine())}


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    me = None                       # set by register; identity is per-connection
    uid = peer_uid(writer.get_extra_info("socket"))
    try:
        while True:
            try:
                line = await reader.readline()
            except ValueError:
                # Longer than MAX_LINE: refuse and close rather than buffer it.
                await send(writer, ok=False, error=f"request exceeds {MAX_LINE} bytes")
                break
            if not line:
                break
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                await send(writer, ok=False, error="malformed JSON")
                continue
            # Every request is an object. A bare list or string used to reach
            # the error handler, whose own audit line called msg.get() and
            # dropped the connection without a reply.
            if not isinstance(msg, dict):
                await send(writer, ok=False, error="a request is a JSON object")
                continue
            try:
                me = await dispatch(msg, me, writer, uid, reader)
            except (ConnectionResetError, asyncio.IncompleteReadError):
                raise
            except Exception as e:
                # One broken request must not take the connection — or, worse,
                # the agent's registration — down with it. The caller gets an
                # error it can report; the audit log gets the reason.
                audit(me or "?", str(msg.get("op")), "-", False,
                      f"internal error: {type(e).__name__}: {e}")
                await send(writer, ok=False,
                           error=f"agentd failed on {msg.get('op')!r}: "
                                 f"{type(e).__name__}: {str(e)[:200]}")
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        if me is not None:
            REG.remove(me)
            audit(me, "unregister", me, True, "connection closed")
        writer.close()


async def send(w: asyncio.StreamWriter, **kw) -> None:
    w.write((json.dumps(kw) + "\n").encode())
    await w.drain()


async def dispatch(msg: dict, me: str | None, w: asyncio.StreamWriter,
                   uid: int | None = None,
                   reader: asyncio.StreamReader | None = None):
    op = msg.get("op")

    if op == "register":
        if me is not None:
            await send(w, ok=False, error=f"already registered as {me}")
            return me
        if "manifest" in msg:
            # Refused rather than ignored: a client that sends grants is either
            # out of date or trying something, and neither should be silent.
            audit(str(msg.get("name")), "register", "-", False,
                  "sent a manifest — grants come from disk, send a name")
            await send(w, ok=False, error="manifests come from the agent tree "
                       "on disk; register with a name, not a manifest")
            return None
        name = str(msg.get("name", ""))
        m = load_manifest(name)
        if m is None:
            audit(name, "register", name, False, "no such agent in the tree")
            await send(w, ok=False, error=f"no agent {name!r} in the agent tree")
            return None
        if name in REG.agents:
            audit(name, "register", name, False, "already live")
            await send(w, ok=False, error=f"{name} is already registered "
                       f"by another connection")
            return None
        if IDENTITY == "uid":
            want = expected_uid(name)
            if want is None or uid != want:
                audit(name, "register", name, False,
                      f"peer uid {uid} is not ainix-{name.replace('/', '-')}")
                await send(w, ok=False, error=f"this process may not act as {name}")
                return None
        REG.add(name, m)
        audit(name, "register", name, True,
              f"tier={m['agent']['tier']} identity={IDENTITY}"
              + ("" if IDENTITY == "uid" else " (UNBOUND: dev mode)"))
        await send(w, ok=True, name=name)
        return name

    if me is None:
        await send(w, ok=False, error="register first")
        return me

    if op == "discover":
        # "*" lists every live agent this caller may task. Discovery never
        # shows an agent the caller could not reach anyway.
        skill = msg.get("skill", "")
        cards = [{"name": n, "tier": v["tier"], **v["card"]}
                 for n, v in REG.agents.items()
                 if (skill == "*" or skill in v["card"].get("skills", []))
                 and may_task(me, n)[0]]
        audit(me, "discover", skill, True, f"{len(cards)} match")
        await send(w, ok=True, cards=cards)

    elif op == "infer":
        ok, why = may_use_model(me, msg["model"])
        served = loaded_model(msg["model"])
        if ok and served and msg["model"].split("-")[0] not in served.lower():
            why += f" — WARNING: runner is serving {served}, not {msg['model']}"
        audit(me, "infer", msg["model"], ok, why)
        if not ok:
            await send(w, ok=False, error=why)
        else:
            r = await asyncio.to_thread(
                infer, msg["model"], msg["messages"],
                msg.get("thinking", False),
                int(policy.clamp(int(msg.get("max_tokens", 512)), 1, MAX_TOKENS)),
                msg.get("temperature"), msg.get("response_format"),
                int(msg.get("logprobs", 0) or 0))
            await send(w, ok=True, content=r["content"], logprobs=r["logprobs"],
                       served=served)

    elif op == "task":
        callee = msg["to"]
        ok, why = may_task(me, callee)
        audit(me, "task", callee, ok, why)
        if not ok:
            await send(w, ok=False, error=why)
        else:
            tid = REG.next_id()
            fut = asyncio.get_running_loop().create_future()
            REG.pending[tid] = (fut, callee)
            await REG.inbox[callee].put(
                {"id": tid, "from": me, "skill": msg.get("skill", ""),
                 "input": msg.get("input")})
            try:
                limit = float(policy.clamp(float(msg.get("timeout", 300)), 1.0,
                                           MAX_TASK_SECONDS))
                out = await asyncio.wait_for(fut, timeout=limit)
                await send(w, ok=True, output=out)
            except asyncio.TimeoutError:
                REG.pending.pop(tid, None)
                await send(w, ok=False, error=f"{callee} did not answer in time")
            except ConnectionError as e:
                await send(w, ok=False, error=str(e))

    elif op == "ask":
        # Intent in, answer out: Laya chooses which agent handles it. Laya
        # decides; agentd enforces. The candidates are exactly the live agents
        # THIS caller may task, Laya's choice is checked against them before
        # anything is forwarded, and the forwarded task runs with the caller's
        # identity — Laya cannot route anyone somewhere they could not go.
        request = str(msg.get("request", ""))[:4000]
        cands = sorted(({"name": n, "description": v["card"].get("description", ""),
                         "skills": v["card"].get("skills", [])}
                        for n, v in REG.agents.items()
                        if n != LAYA and may_task(me, n)[0]),
                       key=lambda c: c["name"])
        if not cands:
            audit(me, "ask", "-", False, "no agent this caller may use is running")
            await send(w, ok=False, error="no agent you may use is running")
            return me
        decision = await laya_decide(me, request, cands)
        pick = decision.get("agent")
        if pick is None:
            audit(me, "ask", "-", False, f"laya: nobody fits ({decision.get('source')})")
            await send(w, ok=False, error="no agent here can do that", decision=decision)
            return me
        if pick not in {c["name"] for c in cands}:
            audit(me, "ask", str(pick), False,
                  "laya chose an agent this caller may not use — refused")
            await send(w, ok=False, error=f"laya chose {pick!r}, which you may not use",
                       decision=decision)
            return me
        audit(me, "ask", pick, True, f"laya: {decision.get('source')} "
              f"(model {decision.get('model_pick')} @ {decision.get('confidence')}, "
              f"keyword {decision.get('keyword_pick')}×{decision.get('keyword_score')})")
        try:
            out = await dispatch_task(me, pick, decision.get("skill") or "",
                                      request, float(msg.get("timeout", 300)))
            await send(w, ok=True, output=out, routed_to=pick, decision=decision)
        except (asyncio.TimeoutError, ConnectionError) as e:
            await send(w, ok=False, error=f"{pick}: {e or 'timed out'}",
                       decision=decision)

    elif op == "next_task":
        # Wait for a task AND for the caller to leave. An agent blocked here
        # sends nothing, so without watching for EOF a killed agent stays
        # registered — and the next task addressed to it is swallowed until it
        # times out.
        get = asyncio.ensure_future(REG.inbox[me].get())
        waiters = {get}
        eof = None
        if reader is not None:
            eof = asyncio.ensure_future(reader.read(1))
            waiters.add(eof)
        done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        if eof is not None and eof in done:
            get.cancel()
            raise ConnectionResetError(f"{me} left while waiting for a task")
        if eof is not None:
            # Cancelling is asynchronous: until the read has actually unwound,
            # the stream still has a waiter, and the next readline() in the
            # handler loop dies with "another coroutine is already waiting".
            eof.cancel()
            try:
                await eof
            except asyncio.CancelledError:
                pass
        await send(w, ok=True, task=get.result())

    elif op == "reply":
        entry = REG.pending.get(msg.get("task_id"))
        # Only the agent the task was sent to may answer it.
        if entry is None or entry[1] != me:
            await send(w, ok=False, error="no such task for you")
            return me
        REG.pending.pop(msg["task_id"], None)
        fut = entry[0]
        if not fut.done():
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
            await send(w, ok=ok, text=path.read_text(encoding="utf-8") if ok else "",
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
        if REG.agents[me]["tier"] != "system":
            audit(me, "status", "-", False, "system tier only")
            await send(w, ok=False, error="status is a system operation")
            return me
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
    server = await asyncio.start_unix_server(handle, str(path), limit=MAX_LINE)
    os.chmod(path, 0o660)
    print(f"agentd listening on {path} | runner {RUNNER} | identity {IDENTITY} | policy {policy.ENGINE}"
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
