#!/usr/bin/env bash
# scripts/check-agent.sh [<tier>/<name>]  — validate agent manifests.
# No arguments: check every agent in the tree.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$root/scripts/check_agent.py" "$root" "${1:-}"
