#!/usr/bin/env bash
# Phase 1 exit criterion: the runner answers a real chat completion.
# Engine-agnostic — both the MAX and llama.cpp runners expose the same contract.
set -euo pipefail

PORT="${PORT:-8000}"
MODEL="${MODEL:-local}"
BASE="http://localhost:${PORT}"
TIMEOUT="${TIMEOUT:-1800}"   # cold start = weight load + graph compile

health() { curl -fsS "${BASE}/health" >/dev/null 2>&1 || curl -fsS "${BASE}/v1/health" >/dev/null 2>&1; }

# A long timeout is right for a runner that is starting — weight load plus
# graph compile is genuinely slow. It is wrong when no runner exists at all:
# waiting 30 minutes for a container nobody started is a hang, not patience.
NAME="${NAME:-ainix-runner}"
if ! health && ! docker ps --filter "name=${NAME}" --filter status=running -q | grep -q .; then
  echo "FAIL: nothing is serving ${BASE} and no ${NAME} container is running." >&2
  echo "      start one first:  make run" >&2
  exit 1
fi

# Something answering /health is not proof it is ours. llama.cpp lists the GGUF
# it has loaded; an unrelated app on the same port does not. Without this, a
# foreign server passes the health gate and the test fails later with a 405
# that points nowhere near the cause.
is_runner() {
  curl -fsS "${BASE}/v1/models" 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
names = [m.get("name") or m.get("id") or "" for m in d.get("models", []) + d.get("data", [])]
owned = [m.get("owned_by", "") for m in d.get("data", [])]
sys.exit(0 if any(n.endswith(".gguf") for n in names) or "llamacpp" in owned else 1)'
}

if health && ! is_runner; then
  echo "FAIL: something is answering on ${BASE}, but it is not an AINIX runner." >&2
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print "      held by "$1" (pid "$2")"}' | sort -u >&2 || true
  echo "      run the runner on another port:  make run PORT=8090 && make smoke PORT=8090" >&2
  exit 1
fi

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

# Name what answered. Any llama.cpp server passes the identity check above, so
# a PASS that does not say which model it tested can be a PASS against someone
# else's server on the same port.
served=$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("model","?"))' 2>/dev/null || echo "?")
echo "PASS ($((t1-t0))s) — served by ${served##*/}"
printf '%s\n' "$content"
