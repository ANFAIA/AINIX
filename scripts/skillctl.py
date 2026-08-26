#!/usr/bin/env python3
"""Skill access control and management.

Levels are ordered by privilege, top to bottom:

    user   — closest to the human, least privileged
    app    — domain work
    system — the foundation, most privileged

A tier may read and modify skills at its own level and at every level *above*
it. It cannot see the levels below: on a real machine those directories are not
mounted into its namespace, so they are absent rather than denied. This module
is the same rule expressed for tooling and for the mount-spec generator.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

# Index 0 is the top (least privileged).
LEVELS = ["user", "app", "system"]


def visible_levels(tier: str) -> list[str]:
    """Levels `tier` may read and modify: its own, plus everything above it."""
    if tier not in LEVELS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {LEVELS}")
    return LEVELS[: LEVELS.index(tier) + 1]


def load(level: str, name: str) -> dict:
    with (SKILLS / level / name / "skill.toml").open("rb") as fh:
        return tomllib.load(fh)["skill"]


def all_skills() -> list[tuple[str, str, dict]]:
    out = []
    for level in LEVELS:
        for d in sorted((SKILLS / level).glob("*/skill.toml")):
            out.append((level, d.parent.name, load(level, d.parent.name)))
    return out


def can(tier: str, level: str, name: str, write: bool) -> tuple[bool, str]:
    """Decide access, and explain the decision. The explanation is the point —
    a rule nobody can predict is a rule nobody can design against."""
    if level not in visible_levels(tier):
        return False, (
            f"{tier} agents cannot see {level} skills — {level} is below {tier}, "
            f"and its directory is not mounted into a {tier} namespace"
        )
    if write:
        try:
            if load(level, name).get("protected"):
                return False, (
                    f"{level}/{name} is protected: changed by human commit only, "
                    f"whatever tier asks"
                )
        except FileNotFoundError:
            return False, f"no such skill: {level}/{name}"
    verb = "modify" if write else "read"
    same = "its own level" if level == tier else f"{level}, which is above {tier}"
    return True, f"{tier} agents may {verb} {same}"


def mount_spec(tier: str) -> list[dict]:
    """What nix/agent.nix mounts for an agent of this tier."""
    return [
        {"source": str(SKILLS / lvl), "target": f"/skills/{lvl}", "mode": "rw"}
        for lvl in visible_levels(tier)
    ]


# --------------------------------------------------------------------------
# cli

DIM, B, OFF = "\033[2m", "\033[1m", "\033[0m"


def cmd_list(argv: list[str]) -> int:
    tier = _opt(argv, "--as")
    levels = visible_levels(tier) if tier else LEVELS
    if tier:
        hidden = [l for l in LEVELS if l not in levels]
        print(f"{DIM}as a {tier} agent"
              + (f" — {', '.join(hidden)} not visible" if hidden else "")
              + f"{OFF}")
    for level in levels:
        rows = [(n, s) for l, n, s in all_skills() if l == level]
        if not rows:
            continue
        print(f"\n  {DIM}{level}{OFF}")
        for name, s in rows:
            tag = f"  {DIM}[protected]{OFF}" if s.get("protected") else ""
            print(f"    {name:16} {s.get('description','')}{tag}")
    print()
    return 0


def cmd_show(argv: list[str]) -> int:
    level, name = _split(argv[0])
    print((SKILLS / level / name / "SKILL.md").read_text())
    return 0


def cmd_can(argv: list[str]) -> int:
    tier = argv[0]
    level, name = _split(argv[1])
    write = "--write" in argv
    ok, why = can(tier, level, name, write)
    print(f"{'ALLOW' if ok else 'DENY '}  {tier} → {'write' if write else 'read'} "
          f"{level}/{name}\n       {why}")
    return 0 if ok else 1


def cmd_new(argv: list[str]) -> int:
    level, name = argv[0], argv[1]
    if level not in LEVELS:
        sys.exit(f"level must be one of {LEVELS}")
    dest = SKILLS / level / name
    if dest.exists():
        sys.exit(f"{dest} already exists")
    dest.mkdir(parents=True)
    (dest / "skill.toml").write_text(
        "[skill]\n"
        f'name        = "{name}"\n'
        f'level       = "{level}"\n'
        'version     = "0.1.0"\n'
        'description = "one line — what this skill does"\n'
        "requires_tools  = []\n"
        "requires_models = []\n"
        "protected   = false\n"
    )
    (dest / "SKILL.md").write_text(
        f"# {name}\n\n"
        "One line on when this applies.\n\n"
        "## Procedure\n\n"
        "1. \n2. \n3. \n\n"
        "## When not to\n\n"
        "The cases where this skill is the wrong tool.\n"
    )
    print(f"created {dest.relative_to(ROOT)}")
    return 0


def cmd_mounts(argv: list[str]) -> int:
    for m in mount_spec(argv[0]):
        print(f"{m['source']}  ->  {m['target']}  ({m['mode']})")
    return 0


def _split(ref: str) -> tuple[str, str]:
    if "/" not in ref:
        sys.exit(f"expected <level>/<name>, got {ref!r}")
    return tuple(ref.split("/", 1))  # type: ignore[return-value]


def _opt(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else None


COMMANDS = {"list": cmd_list, "show": cmd_show, "can": cmd_can,
            "new": cmd_new, "mounts": cmd_mounts}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"usage: skillctl.py {{{'|'.join(COMMANDS)}}} ...\n"
              "  list [--as <tier>]              skills, or only what a tier can see\n"
              "  show <level>/<name>             print SKILL.md\n"
              "  can <tier> <level>/<name> [--write]   explain an access decision\n"
              "  new <level> <name>              scaffold a skill\n"
              "  mounts <tier>                   what gets mounted for that tier")
        return 2
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
