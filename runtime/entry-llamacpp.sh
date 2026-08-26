#!/bin/sh
# Same contract as the MAX runner: OpenAI-compatible API on AINIX_PORT.
set -eu

exec /app/llama-server \
  --model "${AINIX_MODEL_FILE}" \
  --host 0.0.0.0 \
  --port "${AINIX_PORT}" \
  --ctx-size "${AINIX_CTX}" \
  --threads "${AINIX_THREADS}" \
  --jinja \
  "$@"
