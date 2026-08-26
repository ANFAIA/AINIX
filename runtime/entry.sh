#!/bin/sh
# Model runner entrypoint. Env-driven so the same image serves any model;
# extra args are passed straight through to `max serve`.
set -eu

exec /opt/venv/bin/max serve \
  --model-path "${AINIX_MODEL}" \
  --devices "${AINIX_DEVICES}" \
  --port "${AINIX_PORT}" \
  "$@"
