#!/usr/bin/env bash
# scripts/new-agent.sh <tier> <name>  — scaffold a new agent from the template.
set -euo pipefail

usage() { echo "usage: $0 <user|app|system> <name>" >&2; exit 2; }
[ $# -eq 2 ] || usage

tier="$1"; name="$2"
case "$tier" in user|app|system) ;; *) usage ;; esac
[[ "$name" =~ ^[a-z][a-z0-9-]*$ ]] || { echo "name must be kebab-case" >&2; exit 2; }

root="$(cd "$(dirname "$0")/.." && pwd)"
dest="$root/agents/$tier/$name"
[ -e "$dest" ] && { echo "$dest already exists" >&2; exit 1; }

cp -R "$root/agents/_template" "$dest"
sed -i.bak \
  -e "s|^name        = \"example\"|name        = \"$name\"|" \
  -e "s|^tier        = \"app\"|tier        = \"$tier\"|" \
  "$dest/agent.toml"
rm -f "$dest/agent.toml.bak"
sed -i.bak "1s|.*|# $name agent|" "$dest/README.md" && rm -f "$dest/README.md.bak"

if [ "$tier" = "user" ]; then
  # User agents get no model grants — strip the default.
  sed -i.bak 's|^models = .*|models = []|' "$dest/agent.toml" && rm -f "$dest/agent.toml.bak"
fi

echo "created $dest"
echo "next: edit agent.toml, then  make agent-check NAME=$tier/$name"
