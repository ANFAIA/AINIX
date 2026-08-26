"""Outcome-based reward: does the command do the same thing as the reference?

The reward this repo started with asks "did it exit 0". That cannot tell
`sort -r` from `sort -rn` — both run, one answers the question — and it is
exactly why validation shows 39/60 same-utility while `runs` shows 27/60.
Exit status measures whether a command is *well-formed*, never whether it is
*right*.

This measures the effect instead. Candidate and reference each run in an
identical, freshly seeded container; what they print and what they leave on
disk is compared.

    1.0  equivalent   same stdout and same filesystem effect
    0.6  plausible    ran cleanly, different effect (may still be a fair answer
                      to an ambiguous request — worth keeping, worth less)
    0.0  broken       failed to parse, failed to run, or is on the refuse list

Graded rather than binary because rejection sampling needs to rank, not just
filter: a set of 1.0s teaches the shape of a correct answer, and a 0.6 that
outranks a 0.0 still carries signal.
"""

from __future__ import annotations

import hashlib
import json
import subprocess

IMAGE = "debian:stable-slim"
TIMEOUT = 60

# The fixture tree. Both sides see exactly this, so any difference in outcome
# is caused by the command and not by the environment.
SEED = r"""
mkdir -p /testbed /srv/app/data notes /var/log /tmp/work ~/Documents
printf 'alpha\nbravo\ncharlie\n' > /testbed/hello.php
printf 'one\ntwo\nthree\n' > file.txt
printf 'error: disk full\nwarn: slow\nerror: timeout\n' > /var/log/syslog
head -c 4096 /dev/zero > /var/log/big.log
head -c 128  /dev/zero > /var/log/small.log
touch deploy.sh notes/meeting.txt
"""

HARD_REFUSE = ("rm -rf /", "mkfs", ":(){", "dd if=/dev/zero of=/dev/",
               "> /dev/sda", "shutdown", "reboot", "chmod -R 777 /")


_CACHE: dict[str, str] = {}


def _probe(command: str) -> str:
    """Seed a container, run one command, and report what changed.

    stdout and the filesystem are hashed together: two commands are equivalent
    when they print the same thing *and* leave the same tree behind. `ls` and
    `ls > out.txt` print differently and leave different trees; both facts
    matter.
    """
    script = f"""
{SEED}
cd /
out=$( {{ {command} ; }} 2>/dev/null )
rc=$?
echo "RC:$rc"
# Hashed verbatim, NOT sorted. Ordering is the answer for half these
# questions — `ls | sort -r` and `ls -S | head` list the same names in a
# different order, and normalising that away scores them equivalent.
echo "OUT:$(printf '%s' "$out" | md5sum | cut -d' ' -f1)"
echo "FS:$(find /testbed /srv /var/log /tmp/work ~/Documents notes file.txt \
        deploy.sh -printf '%p %s\\n' 2>/dev/null | sort | md5sum | cut -d' ' -f1)"
"""
    if command in _CACHE:
        return _CACHE[command]
    try:
        p = subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", "none",
             "--memory", "512m", "--pids-limit", "128", IMAGE, "sh"],
            input=script, capture_output=True, text=True, timeout=TIMEOUT)
        _CACHE[command] = p.stdout
        return p.stdout
    except subprocess.TimeoutExpired:
        return "RC:124\nOUT:timeout\nFS:timeout\n"


def _parse(raw: str) -> dict:
    d = {}
    for line in raw.splitlines():
        k, _, v = line.partition(":")
        if k in ("RC", "OUT", "FS"):
            d[k] = v
    return d


def score(candidate: str, reference: str | None = None) -> dict:
    """Grade one candidate command. `reference` is the known-good answer; with
    none, this degrades to the old exit-status check and says so."""
    if not candidate or not candidate.strip():
        return {"reward": 0.0, "verdict": "broken", "why": "no command"}
    if any(bad in candidate.lower() for bad in HARD_REFUSE):
        return {"reward": 0.0, "verdict": "broken", "why": "hard-refuse pattern"}

    got = _parse(_probe(candidate))
    if got.get("RC") != "0":
        return {"reward": 0.0, "verdict": "broken",
                "why": f"exit {got.get('RC', '?')}"}

    if reference is None:
        return {"reward": 0.6, "verdict": "plausible",
                "why": "ran cleanly; no reference to compare against"}

    want = _parse(_probe(reference))
    same_out = got.get("OUT") == want.get("OUT")
    same_fs = got.get("FS") == want.get("FS")
    if same_out and same_fs:
        return {"reward": 1.0, "verdict": "equivalent",
                "why": "same output and same filesystem effect"}
    return {"reward": 0.6, "verdict": "plausible",
            "why": ("same output, different files" if same_out else
                    "same files, different output" if same_fs else
                    "different effect")}


def probe_many(commands: list[str]) -> None:
    """Probe many commands in ONE container, re-seeding the fixture between
    each. Container startup dominates the cost — ~1.2 s each — so scoring a
    few hundred candidates one container at a time turns minutes into an hour.
    Results land in the same cache score() reads."""
    todo = [c for c in dict.fromkeys(commands) if c and c not in _CACHE]
    if not todo:
        return
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        parts = []
        for n, cmd in enumerate(chunk):
            parts.append(f"""
rm -rf /testbed /srv /tmp/work notes file.txt deploy.sh /var/log/*.log 2>/dev/null
{SEED}
cd /
echo "###{n}"
out=$( {{ {cmd} ; }} 2>/dev/null )
echo "RC:$?"
echo "OUT:$(printf '%s' "$out" | md5sum | cut -d' ' -f1)"
echo "FS:$(find /testbed /srv /var/log /tmp/work ~/Documents notes file.txt \
        deploy.sh -printf '%p %s\\n' 2>/dev/null | sort | md5sum | cut -d' ' -f1)"
""")
        try:
            p = subprocess.run(
                ["docker", "run", "--rm", "-i", "--network", "none",
                 "--memory", "512m", "--pids-limit", "128", IMAGE, "sh"],
                input="\n".join(parts), capture_output=True, text=True,
                timeout=TIMEOUT * 6)
            blocks = p.stdout.split("###")
        except subprocess.TimeoutExpired:
            blocks = []
        by_index = {}
        for b in blocks[1:]:
            head, _, body = b.partition("\n")
            try:
                by_index[int(head.strip())] = body
            except ValueError:
                continue
        for n, cmd in enumerate(chunk):
            _CACHE[cmd] = by_index.get(n, "RC:124\nOUT:timeout\nFS:timeout\n")


def score_many(pairs: list[tuple[str, str | None]]) -> list[dict]:
    """Grade many at once. Every command — candidate and reference — is probed
    in as few containers as possible first, then graded from the cache."""
    probe_many([c for c, _ in pairs] + [r for _, r in pairs if r])
    return [score(c, r) for c, r in pairs]


if __name__ == "__main__":
    # The cases the exit-status reward gets wrong, and this one does not.
    CASES = [
        ("sort -rn file.txt", "sort -rn file.txt", "identical"),
        ("ls /var/log | sort -r", "ls -S /var/log | head -20",
         "both run; only one answers 'largest'"),
        ("cp /testbed/hello.php /testbed/copy.php",
         "cp /testbed/hello.php /testbed/copy.php", "identical mutation"),
        ("touch /testbed/a.txt", "touch /testbed/b.txt",
         "both succeed, different file"),
        ("cat /nope", "cat file.txt", "candidate fails"),
    ]
    for cand, ref, note in CASES:
        r = score(cand, ref)
        print(f"{r['reward']:>4}  {r['verdict']:<10} {note}")
        print(f"      {cand}   vs   {ref}   — {r['why']}")
