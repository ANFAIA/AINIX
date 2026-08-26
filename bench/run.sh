#!/usr/bin/env bash
# Generation throughput, as reported by the engine itself.
set -euo pipefail
PORT="${PORT:-8000}"
curl -fsS "http://localhost:${PORT}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"local","messages":[{"role":"user","content":"Write a 200 word explanation of virtual memory."}],"max_tokens":256}' \
  | python3 "$(dirname "$0")/report.py"
