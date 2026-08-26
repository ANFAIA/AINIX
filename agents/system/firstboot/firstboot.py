"""AINIX first-boot setup.

Two questions, in this order:

1. Is there a network? Everything else depends on the answer, and a machine
   with no network must still end up at a usable shell rather than a dead end.
2. Which model should this machine run? The default is stated, the catalog is
   offered, and nothing is downloaded without a choice.

Runs once. State lives in AINIX_STATE (default /var/lib/ainix/state.toml, or
~/.local/state/ainix/state.toml when not running as root).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tomllib
from pathlib import Path

# On the built image the script lives at /etc/ainix/firstboot/ and the catalog
# at /etc/ainix/models.toml, so neither path can be derived from __file__.
ROOT = Path(__file__).resolve().parents[3]
CATALOG = Path(os.environ.get("AINIX_CATALOG", ROOT / "models.toml"))
FETCH = Path(os.environ.get("AINIX_FETCH", ROOT / "scripts" / "fetch-model.sh"))

# Reached only to fetch weights, and only after the user asks for a download.
PROBE_HOST = os.environ.get("AINIX_PROBE_HOST", "huggingface.co")
PROBE_PORT = 443
PROBE_TIMEOUT = 4.0

B = "\033[1m"
DIM = "\033[2m"
OFF = "\033[0m"


# --------------------------------------------------------------------------
# state


def state_path() -> Path:
    if env := os.environ.get("AINIX_STATE"):
        return Path(env)
    if os.geteuid() == 0:
        return Path("/var/lib/ainix/state.toml")
    return Path.home() / ".local/state/ainix/state.toml"


def already_done() -> bool:
    p = state_path()
    if not p.exists():
        return False
    with p.open("rb") as fh:
        return bool(tomllib.load(fh).get("firstboot", {}).get("complete"))


def write_state(model: str, online: bool) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# Written by agents/system/firstboot. Delete to run setup again.\n"
        "[firstboot]\n"
        "complete = true\n"
        f"online = {str(online).lower()}\n"
        "\n[model]\n"
        f'default = "{model}"\n'
    )


# --------------------------------------------------------------------------
# catalog


def weights_dir() -> Path:
    return Path(os.environ.get("AINIX_WEIGHTS", Path.home() / ".cache/ainix/weights"))


def load_catalog() -> tuple[dict, dict]:
    with CATALOG.open("rb") as fh:
        catalog = tomllib.load(fh)
    return catalog, catalog.pop("remote", {})


def total_ram_gb() -> float | None:
    """Best-effort RAM size, so the catalog can say what actually fits."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True
            )
            return int(out.stdout) / 1024**3
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024**2
    except Exception:
        return None
    return None


def size_gb(spec: str) -> float:
    """Parse the catalog's size field ('769MB', '~5.5GB') into GB."""
    s = spec.strip().lstrip("~").upper()
    try:
        if s.endswith("MB"):
            return float(s[:-2]) / 1024
        if s.endswith("GB"):
            return float(s[:-2])
    except ValueError:
        pass
    return 0.0


def have_locally(model: dict) -> bool:
    return (weights_dir() / model.get("file", "")).exists()


# --------------------------------------------------------------------------
# network


def check_network() -> bool:
    try:
        socket.setdefaulttimeout(PROBE_TIMEOUT)
        with socket.create_connection((PROBE_HOST, PROBE_PORT), PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def offer_network() -> bool:
    """No connectivity. Say what that costs, offer the ways out, do not nag."""
    print(f"\n  {B}No network.{OFF}")
    print("  Models cannot be downloaded until this machine is online.\n")

    tools = [
        ("nmtui", "configure wi-fi or ethernet"),
        ("nmcli", "configure the network from the command line"),
        ("iwctl", "connect to wi-fi"),
    ]
    available = [(cmd, desc) for cmd, desc in tools if shutil.which(cmd)]

    for i, (cmd, desc) in enumerate(available, 1):
        print(f"    {i}. {cmd:8} — {desc}")
    print(f"    {len(available) + 1}. continue offline")

    choice = ask(f"\n  Choice [{len(available) + 1}]: ", str(len(available) + 1))
    if choice.isdigit() and 1 <= int(choice) <= len(available):
        subprocess.run([available[int(choice) - 1][0]])
        return check_network()
    return False


# --------------------------------------------------------------------------
# ui


def ask(prompt: str, default: str) -> str:
    if not sys.stdin.isatty() or "--yes" in sys.argv:
        print(f"{prompt}{default}   {DIM}(non-interactive){OFF}")
        return default
    try:
        return input(prompt).strip() or default
    except (EOFError, KeyboardInterrupt):
        print()
        return default


TIERS = [
    ("small — runs on CPU, on anything", 0.0, 3.0),
    ("mid — small GPU, or a patient CPU", 3.0, 10.0),
    ("large — real GPU territory", 10.0, 999.0),
]


def show_catalog(catalog: dict, remote: dict, ram: float | None, online: bool) -> list[str]:
    """Print the catalog grouped by size. Returns names in display order."""
    order: list[str] = []
    n = 0
    for label, lo, hi in TIERS:
        rows = [(k, v) for k, v in catalog.items() if lo <= size_gb(v.get("size", "")) < hi]
        if not rows:
            continue
        print(f"\n  {DIM}{label}{OFF}")
        for name, m in rows:
            n += 1
            order.append(name)
            marks = []
            if m.get("default"):
                marks.append("default")
            if have_locally(m):
                marks.append("downloaded")
            elif not online:
                marks.append("needs network")
            elif ram and size_gb(m.get("size", "")) * 1.4 > ram:
                marks.append("too big for this machine")
            tag = f"  {DIM}[{', '.join(marks)}]{OFF}" if marks else ""
            print(f"    {n:2}. {name:16} {m.get('size',''):>8}  {m.get('role','')}{tag}")

    if remote:
        print(f"\n  {DIM}remote — third-party APIs, off until you add a key{OFF}")
        for name, m in remote.items():
            print(f"        {'remote.' + name:24}  {m.get('role','')}")
        print(f"    {DIM}enable in models.toml; the key stays with agentd, "
              f"never with an agent{OFF}")

    return order


# --------------------------------------------------------------------------
# main


def run() -> int:
    if already_done() and "--force" not in sys.argv:
        return 0

    catalog, remote = load_catalog()
    ram = total_ram_gb()
    default = next((k for k, v in catalog.items() if v.get("default")), next(iter(catalog)))

    print(f"\n{B}AINIX{OFF} — first boot\n")
    print("  Checking network…", end=" ", flush=True)
    online = check_network()
    print("connected" if online else "none")
    if not online:
        online = offer_network()

    print(f"\n  Default model: {B}{default}{OFF}"
          f"  {DIM}({catalog[default].get('size','')}, "
          f"{catalog[default].get('role','')}){OFF}")
    if ram:
        print(f"  This machine: {DIM}{ram:.0f} GB RAM{OFF}")

    if have_locally(catalog[default]):
        print(f"  {DIM}Already downloaded — ready to run.{OFF}")
    elif not online:
        print(f"  {DIM}Not downloaded, and no network. Shell only until you connect.{OFF}")

    answer = ask(f"\n  Use {default}, or see the full catalog? [use/list]: ", "use")
    chosen = default

    if answer.lower().startswith(("l", "s")):
        order = show_catalog(catalog, remote, ram, online)
        pick = ask(f"\n  Model [{default}]: ", default)
        if pick.isdigit() and 1 <= int(pick) <= len(order):
            chosen = order[int(pick) - 1]
        elif pick in catalog:
            chosen = pick
        else:
            print(f"  {DIM}Unknown model {pick!r} — keeping {default}.{OFF}")

    model = catalog[chosen]
    if not have_locally(model):
        if not online:
            print(f"\n  Cannot download {chosen} offline. Dropping to a shell; "
                  f"run `ainix-firstboot` again once connected.")
            write_state(chosen, online)
            return 1
        print(f"\n  Downloading {chosen} ({model.get('size','')})…\n")
        rc = subprocess.run([str(FETCH), chosen], cwd=ROOT).returncode
        if rc != 0:
            print(f"\n  Download failed. Fix the network and run `ainix-firstboot` again.")
            return rc

    write_state(chosen, online)
    print(f"\n  {B}Ready.{OFF}  {chosen} is this machine's default model.")
    print(f"  {DIM}Change it any time:  ainix-firstboot --force{OFF}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
