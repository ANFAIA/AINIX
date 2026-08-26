"""Validate AINIX agent manifests.

The same rules Nix enforces at build time, runnable without Nix so a contributor
gets the error in a second instead of after a build.
"""

import sys
import tomllib
from pathlib import Path

TIERS = {"user", "app", "system"}
# Skill levels, top (least privileged) to bottom (most privileged). A tier sees
# its own level and every level above it — see scripts/skillctl.py.
SKILL_LEVELS = ["user", "app", "system"]
# Callable-from rules: who is allowed to name whom as a peer.
CALLABLE = {"user": {"app"}, "app": {"app"}, "system": {"user", "app", "system"}}
EVOLUTION_MODES = {"self", "parent", "frozen"}
# Never rewritable by an agent or its parent — only by a human commit.
IMMUTABLE_FIELDS = {"tier", "quota", "models", "tools", "peers"}


def load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def visible_skill_levels(tier: str) -> list[str]:
    return SKILL_LEVELS[: SKILL_LEVELS.index(tier) + 1]


def check(agent_dir: Path, root: Path, models: set[str], known: set[str]) -> list[str]:
    rel = agent_dir.relative_to(root / "agents")
    errs: list[str] = []
    m = load(agent_dir / "agent.toml")
    a = m.get("agent", {})
    ref = str(rel)

    tier = a.get("tier")
    if tier not in TIERS:
        return [f"{ref}: tier must be one of {sorted(TIERS)}, got {tier!r}"]
    if rel.parts[0] != tier:
        errs.append(f"{ref}: tier {tier!r} does not match directory {rel.parts[0]!r}")
    if a.get("name") != rel.parts[1]:
        errs.append(f"{ref}: name {a.get('name')!r} does not match directory")

    entry = a.get("entrypoint", "main.mojo")
    if not (agent_dir / entry).exists():
        errs.append(f"{ref}: entrypoint {entry!r} does not exist")

    for model in a.get("models", []):
        if model not in models:
            errs.append(f"{ref}: grants model {model!r}, not declared in models.toml")
    if tier == "user" and a.get("models"):
        errs.append(f"{ref}: user agents may not hold model grants — route through an app agent")

    visible = visible_skill_levels(tier)
    for skill in a.get("skills", []):
        found = [lvl for lvl in SKILL_LEVELS
                 if (root / "skills" / lvl / skill / "skill.toml").exists()]
        if not found:
            errs.append(f"{ref}: skill {skill!r} does not exist")
        elif not set(found) & set(visible):
            errs.append(f"{ref}: skill {skill!r} is at level {found[0]!r}, "
                        f"which a {tier} agent cannot see")

    for peer in a.get("peers", []):
        if peer not in known:
            errs.append(f"{ref}: peer {peer!r} does not exist")
            continue
        peer_tier = peer.split("/", 1)[0]
        if peer_tier not in CALLABLE[tier]:
            errs.append(f"{ref}: a {tier} agent may not call a {peer_tier} agent ({peer})")

    ev = m.get("evolution", {})
    mode = ev.get("mode", "frozen")
    if mode not in EVOLUTION_MODES:
        errs.append(f"{ref}: evolution.mode must be one of {sorted(EVOLUTION_MODES)}")
    if mode == "parent":
        parent = ev.get("parent")
        if not parent:
            errs.append(f"{ref}: evolution.mode = 'parent' requires evolution.parent")
        elif parent not in known:
            errs.append(f"{ref}: evolution.parent {parent!r} does not exist")
    bad = IMMUTABLE_FIELDS & set(ev.get("allow", []))
    if bad:
        errs.append(f"{ref}: evolution.allow may never contain {sorted(bad)} — an agent "
                    f"cannot widen its own access")
    if tier == "system" and mode != "frozen":
        errs.append(f"{ref}: system agents must be evolution.mode = 'frozen'")

    if not m.get("card", {}).get("description"):
        errs.append(f"{ref}: card.description is required — it is how peers discover you")

    return errs


def main() -> int:
    root = Path(sys.argv[1])
    only = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None

    catalog = load(root / "models.toml")
    # Local runners are top-level tables; remote providers live under [remote.*]
    # and are granted as "remote.<name>".
    models = {k for k in catalog if k != "remote"}
    models |= {f"remote.{k}" for k in catalog.get("remote", {})}
    dirs = sorted(
        p.parent for p in (root / "agents").glob("*/*/agent.toml")
        if p.parent.parent.name in TIERS
    )
    known = {str(d.relative_to(root / "agents")) for d in dirs}

    if only:
        dirs = [d for d in dirs if str(d.relative_to(root / "agents")) == only]
        if not dirs:
            print(f"no such agent: {only}", file=sys.stderr)
            return 2

    errs = [e for d in dirs for e in check(d, root, models, known)]
    for e in errs:
        print(f"error: {e}", file=sys.stderr)
    print(f"{len(dirs)} agent(s) checked, {len(errs)} error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
