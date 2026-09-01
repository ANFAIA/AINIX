"""Have a model author an agent tree, then hold it to the same rules as a human.

The interesting question is not whether a model can write TOML. It is whether
an org chart in English can become a *checkable* structure — grants, clearances,
peer edges — that the validator will argue with. So generation is only half of
this; the other half is running check_agent.py on the result and reporting what
the model got wrong rather than quietly repairing it.

    export OPENROUTER_API_KEY=...
    python3 scripts/generate_org.py --brief examples/orgs/globex.md --out examples/globex
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "training"))
from generate import ask, load_teacher            # noqa: E402

CONTRACT = """You design agent organisations for AINIX, a Linux distribution
where every process is an agent holding exactly the capabilities its manifest
grants.

Rules the design MUST satisfy. A design that breaks one is rejected by a
validator, not by a reviewer:

TIERS
- `user` — the human surfaces. Holds NO model grants and NO clearance above the
  lowest level. Anything it cannot do itself it asks an app agent to do.
- `app` — the domain experts. Model grants, tool grants, and clearance live here.
- `system` — keeps the others alive. Rare. Must be evolution.mode = "frozen".
- A user agent may name only app agents as peers. An app agent may name only
  app agents. Nothing may name a user agent as a peer.
- Every peer is written "<tier>/<name>" with a slash, exactly as the agent's own
  tier and name appear: "app/knowledge-broker". Not "knowledge.broker", not
  "knowledge-broker". A dot is not a separator and a bare name is not a peer.

GROUPS AND CLEARANCE
- Every agent belongs to exactly one group.
- Clearance levels, lowest to highest: public, internal, confidential, restricted.
- A group declares the highest clearance its agents may hold. An agent may hold
  LESS than its group, never more.
- Give each agent the LOWEST clearance that still lets it work. An agent that
  reads untrusted external content (web pages, email, user uploads) must hold
  `public` — it is the one most likely to be turned against you.
- `restricted` is for credentials, personal data, and legal matters — material
  whose leak harms a PERSON. Commercial secrecy is `confidential`. A finance or
  strategy function is confidential, not restricted. Over-classifying is not
  the safe default it looks like: when everything is restricted, the label stops
  meaning anything and nobody can do their job.
- An agent at `restricted` must also carry "justification": one sentence naming
  the material that needs it. If you cannot name credentials, personal data, or
  a legal matter, the agent is `confidential` and not `restricted`.
- Every skill you attach to a `user` agent must itself be level "user". A user
  agent cannot see app-level skills, so granting it one is rejected. If the
  skill is about the human surface — routing, rendering, confirming — it IS a
  user skill; write it at that level rather than raising what the console sees.

DESIGN RULES
- No agent gets a tool it does not use, or a peer it never calls.
- An agent that writes something public returns a draft; a human approves the
  publish. Never grant an agent a tool that publishes without review.
- One agent should hold custody of documents and broker every read against the
  requester's clearance. Others never open a document directly.

Answer with ONLY a JSON object, no prose and no code fence:

{
  "groups": {"<name>": {"description": "...", "clearance": "internal"}},
  "agents": [
    {"name": "...", "tier": "app", "group": "...", "clearance": "internal",
     "justification": "only when clearance is restricted",
     "domain": "one line, lowercase, what it is for",
     "models": ["..."], "tools": ["..."], "peers": ["app/other"],
     "card": "one sentence a peer reads to decide whether to call it",
     "card_skills": ["ns.verb"],
     "skills": [{"name": "kebab-case", "level": "app",
                 "description": "one line",
                 "procedure": ["step", "step", "step"],
                 "never": "the thing this skill must not do"}]}
  ]
}

Model names must come from this catalog: %s
"""


def extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def justification_line(a: dict) -> str:
    j = (a.get("justification") or "").strip()
    return f"justification = {json.dumps(j)}\n" if j else ""


def normalise_peers(spec: dict) -> list[str]:
    """Repair peer references the model wrote in the wrong shape.

    Only the mechanical cases: a dot instead of a slash, or a bare name that
    matches exactly one agent. A peer that resolves to nothing is left broken
    for the validator to reject — inventing an edge the design did not ask for
    would be worse than a failed check.
    """
    by_name = {a["name"]: f"{a['tier']}/{a['name']}" for a in spec["agents"]}
    fixed = []
    for a in spec["agents"]:
        out = []
        for p in a.get("peers", []):
            if p in by_name.values():
                out.append(p)
                continue
            bare = p.split("/")[-1].split(".")[-1]
            guess = by_name.get(bare) or by_name.get(p.replace(".", "-"))
            if guess:
                fixed.append(f"{a['tier']}/{a['name']}: {p!r} -> {guess!r}")
                out.append(guess)
            else:
                out.append(p)
        a["peers"] = out
    return fixed


def write_org(spec: dict, out: Path, catalog: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "models.toml").write_text(catalog.read_text())

    levels = ["public", "internal", "confidential", "restricted"]
    lines = ["# Generated. Clearance is granted to a group; an agent may hold",
             "# at most its group's level.", "",
             "[levels]", f"order = {json.dumps(levels)}", ""]
    for g, v in spec["groups"].items():
        lines += [f"[groups.{g}]",
                  f'description = {json.dumps(v.get("description", ""))}',
                  f'clearance   = {json.dumps(v.get("clearance", "internal"))}', ""]
    (out / "groups.toml").write_text("\n".join(lines))

    for a in spec["agents"]:
        d = out / "agents" / a["tier"] / a["name"]
        d.mkdir(parents=True, exist_ok=True)
        frozen = a["tier"] == "system"
        (d / "agent.toml").write_text(f"""[agent]
name       = {json.dumps(a["name"])}
tier       = {json.dumps(a["tier"])}
group      = {json.dumps(a["group"])}
domain     = {json.dumps(a.get("domain", ""))}
version    = "0.1.0"
entrypoint = "main.mojo"

models = {json.dumps(a.get("models", []))}
tools  = {json.dumps(a.get("tools", []))}
skills = {json.dumps([s["name"] for s in a.get("skills", [])])}
peers  = {json.dumps(a.get("peers", []))}

[documents]
clearance = {json.dumps(a.get("clearance", "public"))}
{justification_line(a)}
[quota]
memory = "1Gi"
cpu    = "1"
gpu    = "0"

[card]
description = {json.dumps(a.get("card", ""))}
skills      = {json.dumps(a.get("card_skills", []))}
inputs      = "text"
outputs     = "json"

[evolution]
mode   = {json.dumps("frozen" if frozen else "self")}
allow  = {json.dumps([] if frozen else ["card", "prompt"])}
review = "required"
""")
        (d / "main.mojo").write_text(f"""# {a.get("domain", a["name"])}

from std.python import Python


def main() raises:
    var ainix = Python.import_module("ainix_agent")
    var agent = ainix.Agent.from_manifest("agent.toml")

    while True:
        var task = agent.next_task()
        if not task:
            break
        agent.reply(task, agent.handle(task))
""")
        for s in a.get("skills", []):
            sd = out / "skills" / s.get("level", a["tier"]) / s["name"]
            sd.mkdir(parents=True, exist_ok=True)
            (sd / "skill.toml").write_text(f"""[skill]
name        = {json.dumps(s["name"])}
level       = {json.dumps(s.get("level", a["tier"]))}
version     = "0.1.0"
description = {json.dumps(s.get("description", ""))}
requires_tools  = []
requires_models = []
protected   = false
""")
            steps = "\n".join(f"{i}. {t}" for i, t in
                              enumerate(s.get("procedure", []), 1))
            (sd / "SKILL.md").write_text(
                f"# {s['name']}\n\n{s.get('description','')}\n\n"
                f"## Procedure\n\n{steps}\n\n"
                f"## Never\n\n{s.get('never','')}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brief", required=True, help="the org, in English")
    ap.add_argument("--out", required=True)
    ap.add_argument("--catalog", default="examples/acme/models.toml")
    ap.add_argument("--teacher", default="remote.minimax-m3")
    args = ap.parse_args()

    catalog = ROOT / args.catalog
    import tomllib
    with catalog.open("rb") as fh:
        cat = tomllib.load(fh)
    names = [k for k in cat if k != "remote"] + \
            [f"remote.{k}" for k in cat.get("remote", {})]

    brief = (ROOT / args.brief).read_text()
    teacher = load_teacher(args.teacher)
    print(f"asking {args.teacher} to design the org…")
    raw = ask(teacher, CONTRACT % json.dumps(names) + "\n\nThe organisation:\n"
              + brief, timeout=600, retries=3)
    spec = extract_json(raw)
    if spec is None:
        print("the model did not return usable JSON:", raw[:400], file=sys.stderr)
        return 1

    fixed = normalise_peers(spec)
    if fixed:
        print(f"\nrepaired {len(fixed)} peer reference(s) the model wrote in the "
              f"wrong shape:")
        for f in fixed[:8]:
            print(f"  {f}")
        if len(fixed) > 8:
            print(f"  … and {len(fixed) - 8} more")

    out = ROOT / args.out
    write_org(spec, out, catalog)
    n_agents = len(spec["agents"])
    n_skills = sum(len(a.get("skills", [])) for a in spec["agents"])
    print(f"wrote {n_agents} agents, {len(spec['groups'])} groups, "
          f"{n_skills} skills -> {args.out}\n")

    # The point of the exercise: hold the generated tree to the same rules.
    print("validating what it produced:")
    return subprocess.run([sys.executable, str(ROOT / "scripts/check_agent.py"),
                           str(out)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
