"""Print the model catalog: local runners, then remote providers."""

import tomllib
from pathlib import Path

catalog = tomllib.load((Path(__file__).parent.parent / "models.toml").open("rb"))
remote = catalog.pop("remote", {})

for name, m in catalog.items():
    flag = "  (default)" if m.get("default") else ""
    print(f"{name:16} {m.get('size',''):>8}  {m.get('devices',''):3}  {m.get('role','')}{flag}")

if remote:
    print()
    for name, m in remote.items():
        state = "enabled" if m.get("enabled") else "disabled"
        print(f"{'remote.'+name:16} {state:>8}  {m.get('provider',''):11}  {m.get('role','')}")
