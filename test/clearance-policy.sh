#!/usr/bin/env bash
# Document clearance, enforced at runtime rather than only validated.
#
# Runs agentd against the ACME example, whose agents span every level, and
# asserts that each one sees exactly the documents its clearance covers — and
# that a document it cannot open is ABSENT from the listing, not shown and
# refused. A title is a disclosure too.
set -u
cd "$(dirname "$0")/.."

export AINIX_SOCK=${TMPDIR:-/tmp}/ainix-clearance-$$.sock
export AINIX_ROOT=$PWD/examples/acme
export PYTHONPATH=$PWD/agents/lib
PY=${PY:-python3}

$PY agents/system/agentd/agentd.py 2>"${TMPDIR:-/tmp}/agentd-clearance.log" &
AGENTD=$!
trap 'kill $AGENTD 2>/dev/null; rm -f "$AINIX_SOCK"' EXIT
# Ready means accepting connections. A socket FILE can be left over from a
# killed run, and testing for it (-S) raced the broker's startup.
for _ in $(seq 100); do
  $PY -c "import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])" \
    "$AINIX_SOCK" 2>/dev/null && break
  sleep 0.1
done

pass=0; fail=0
check() { # check <name> <expected> <python expression printing a result>
  local name=$1 want=$2 code=$3 got
  got=$($PY -c "
import sys, tomllib
sys.path.insert(0, 'agents/lib')
from ainix_agent import Agent, Conn, Denied
def load(p):
    a = Agent.__new__(Agent); a._conn = Conn()
    with open(p,'rb') as fh: a.manifest = tomllib.load(fh)
    x = a.manifest['agent']; a.name=f\"{x['tier']}/{x['name']}\"; a.tier=x['tier']
    a._conn.call('register', name=a.name)
    return a
try:
    print($code)
except Denied as e:
    print('DENIED')
" 2>/dev/null)
  if [ "$got" = "$want" ]; then
    printf '  \033[32mok\033[0m   %-52s %s\n' "$name" "$got"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m %-52s want %s, got %s\n' "$name" "$want" "$got"; fail=$((fail+1))
  fi
}

A=examples/acme/agents/app
echo "document clearance"
check "public agent sees only the public document"        1 \
  "len(load('$A/article-scout/agent.toml').documents())"
check "internal agent sees public + internal"             2 \
  "len(load('$A/social-media/agent.toml').documents())"
check "confidential agent adds the roadmap"               3 \
  "len(load('$A/competitors/agent.toml').documents())"
check "the librarian sees everything it guards"           4 \
  "len(load('$A/librarian/agent.toml').documents())"

echo
echo "reads across the line"
check "marketing may read the content calendar"           internal \
  "load('$A/social-media/agent.toml').document('q3-content-calendar')['classification']"
check "marketing may NOT read the roadmap"                DENIED \
  "load('$A/social-media/agent.toml').document('roadmap-h2')"
check "the scout that reads the web gets nothing internal" DENIED \
  "load('$A/article-scout/agent.toml').document('q3-content-calendar')"
check "nobody but the librarian reads personal records"   DENIED \
  "load('$A/competitors/agent.toml').document('employee-handbook-appendix')"
check "the librarian does"                                restricted \
  "load('$A/librarian/agent.toml').document('employee-handbook-appendix')['classification']"

echo
echo "the exploit this suite once missed"
# Before identity came from disk, any process could register with a manifest it
# wrote itself — clearance included — and read these records. Kept as a test so
# the hole cannot quietly reopen.
check "a forged restricted manifest reads nothing"     DENIED \
  "Conn().call('register', manifest={'agent':{'name':'evil','tier':'system'},'documents':{'clearance':'restricted'}})"
check "an invented agent name reads nothing"           DENIED \
  "Conn().call('register', name='system/evil')"

echo
echo "tool grants"
check "granted tool resolves"                             linkedin-post \
  "load('$A/social-media/agent.toml').tool('linkedin-post').name"
check "ungranted tool is refused"                         DENIED \
  "load('$A/article-scout/agent.toml').tool('cms-write')"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
