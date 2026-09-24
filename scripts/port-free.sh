#!/usr/bin/env bash
# Fail early and clearly if a port is taken by anything that is not our runner.
#
# Docker publishes on 0.0.0.0, so a process already bound to 127.0.0.1 on the
# same port does not stop `docker run` — both bind, and every request to
# localhost reaches the OTHER process. The runner looks up, the smoke test sees
# a healthy /health, and the first real request fails with a 405 from an app
# that has nothing to do with AINIX. Check first.
set -euo pipefail
PORT=${1:?port}
NAME=${2:-ainix-runner}

holder=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $1" (pid "$2")"}' | sort -u | head -3 || true)
[ -z "$holder" ] && exit 0

# Our own container's port proxy is fine — `make run` replaces it.
if docker ps --filter "name=^/${NAME}$" --format '{{.Ports}}' 2>/dev/null | grep -q ":${PORT}->"; then
  exit 0
fi

# Suggest a port that is actually free, not a fixed one that may be taken too.
free=
for p in $(seq 8090 8199); do
  if ! lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then free=$p; break; fi
done
echo "port ${PORT} is already in use by: ${holder}" >&2
echo "that is not ${NAME}. Use a free one:  make run PORT=${free:-<free port>}" >&2
exit 1
