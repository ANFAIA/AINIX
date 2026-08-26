#!/usr/bin/env bash
# Phase 1 exit criterion: the runner answers a real chat completion.
# Engine-agnostic — both the MAX and llama.cpp runners expose the same contract.
set -euo pipefail

PORT="${PORT:-8000}"
MODEL="${MODEL:-local}"
BASE="http://localhost:${PORT}"
TIMEOUT="${TIMEOUT:-1800}"   # cold start = weight load + graph compile

health() { curl -fsS "${BASE}/health" >/dev/null 2>&1 || curl -fsS "${BASE}/v1/health" >/dev/null 2>&1; }

echo "waiting for ${BASE} (up to ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
until health; do
  [ "$(date +%s)" -lt "$deadline" ] || { echo "FAIL: server never became healthy" >&2; exit 1; }
  sleep 5
done

t0=$(date +%s)
resp=$(curl -fsS "${BASE}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"In one sentence: what is a Linux kernel?\"}],\"max_tokens\":64}")
t1=$(date +%s)

content=$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])')
[ -n "${content// /}" ] || { echo "FAIL: empty completion" >&2; printf '%s\n' "$resp" >&2; exit 1; }

echo "PASS ($((t1-t0))s)"
printf '%s\n' "$content"
