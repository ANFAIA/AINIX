#!/usr/bin/env bash
# scripts/fetch-model.sh <name>  — download a model listed in models.toml.
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: $0 <model-name>   (names: $(python3 -c "
import tomllib,sys
d=tomllib.load(open('models.toml','rb'))
print(' '.join(k for k in d if k!='remote'))")) " >&2; exit 2; }

root="$(cd "$(dirname "$0")/.." && pwd)"
dest="${AINIX_WEIGHTS:-$HOME/.cache/ainix/weights}"
mkdir -p "$dest"

read -r repo file < <(python3 - "$root/models.toml" "$1" <<'PY'
import sys, tomllib
catalog = tomllib.load(open(sys.argv[1], "rb"))
m = catalog.get(sys.argv[2])
if m is None or "repo" not in m:
    sys.exit(f"no local model named {sys.argv[2]!r} in models.toml")
print(m["repo"], m["file"])
PY
)

if [ -f "$dest/$file" ]; then
  echo "already have $dest/$file"
  exit 0
fi

echo "fetching $repo/$file -> $dest"
curl -fL --progress-bar -o "$dest/$file" \
  "https://huggingface.co/$repo/resolve/main/$file"
ls -lh "$dest/$file"
