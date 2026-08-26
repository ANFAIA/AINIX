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
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"In one sentence: what is a Linux kernel?\"}],\"max_tokens\":512,\"chat_template_kwargs\":{\"enable_thinking\":false}}")
t1=$(date +%s)

# `enable_thinking: false` above matters: reasoning models (Qwen3.5, gpt-oss)
# otherwise spend the whole token budget in `reasoning_content` and return an
# empty `content`. A smoke test wants the answer, not the deliberation.
content=$(printf '%s' "$resp" | python3 -c '
import json, sys
m = json.load(sys.stdin)["choices"][0]["message"]
answer = (m.get("content") or "").strip()
if answer:
    print(answer)
elif (m.get("reasoning_content") or "").strip():
    sys.exit("REASONING_ONLY")
')
if [ "$content" = "" ]; then
  echo "FAIL: no answer — the model produced only reasoning within the token budget," >&2
  echo "      or nothing at all. Raise max_tokens, or disable thinking mode." >&2
  exit 1
fi

echo "PASS ($((t1-t0))s)"
printf '%s\n' "$content"
