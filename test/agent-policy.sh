#!/usr/bin/env bash
# The negative tests matter more than the happy path: a capability system is
# only worth anything if it fails closed. Each case is something an agent might
# plausibly try, and each denial must carry the RIGHT reason — a test that
# accepts any refusal passes just as happily when the system refuses for a
# reason that has nothing to do with the rule under test.
set -u
cd "$(dirname "$0")/.."

TMP=${TMPDIR:-/tmp}
export AINIX_SOCK=${AINIX_SOCK:-$TMP/ainix-test-agentd.sock}
export AINIX_ROOT=$PWD
export PYTHONPATH=$PWD/agents/lib
PY=${PY:-python3}

$PY agents/system/agentd/agentd.py 2>"$TMP/agentd-policy.log" &
AGENTD=$!
STUB=
trap 'kill $AGENTD $STUB 2>/dev/null; rm -f "$AINIX_SOCK"' EXIT
for _ in $(seq 50); do [ -S "$AINIX_SOCK" ] && break; sleep 0.1; done

pass=0; fail=0
check() { # check <name> <allow|deny> <python statement> [substring the denial must contain]
  local name=$1 expect=$2 code=$3 why=${4:-} out
  out=$($PY -c "
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
    $code
    print('ALLOW')
except Denied as e:
    print('DENY', e)
except Exception as e:
    print('ERROR', type(e).__name__, e)
" 2>&1)
  local got=${out%% *} ok=0
  if [ "$expect" = allow ] && [ "$got" = ALLOW ]; then ok=1; fi
  if [ "$expect" = deny ] && [ "$got" = DENY ]; then
    if [ -z "$why" ] || [[ "$out" == *"$why"* ]]; then ok=1; fi
  fi
  if [ $ok = 1 ]; then
    printf '  \033[32mok\033[0m   %-46s %s\n' "$name" "${out#* }"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m %-46s want %s%s, got: %s\n' "$name" "$expect" \
      "${why:+ ($why)}" "$out"; fail=$((fail+1))
  fi
}

SHELL_M=agents/user/shell/agent.toml
EXPERT_M=agents/app/shell-expert/agent.toml

echo "identity — the manifest comes from disk, never from the caller"
check "a forged manifest is refused"               deny \
  "Conn().call('register', manifest={'agent':{'name':'evil','tier':'system'}})" \
  "register with a name"
check "an agent not in the tree is refused"        deny \
  "Conn().call('register', name='system/evil')"     "no agent 'system/evil'"
check "a path-traversal name is refused"           deny \
  "Conn().call('register', name='app/../../etc')"   "no agent"
check "unregistered connection is refused"         deny \
  "Conn().call('infer', model='gemma-3-1b', messages=[])" "register first"
check "one connection cannot register twice"       deny \
  "a = load('$SHELL_M'); a._conn.call('register', name='app/shell-expert')" \
  "already registered as user/shell"

echo
echo "capabilities"
check "user agent may not use a model"             deny \
  "load('$SHELL_M')._conn.call('infer', model='gemma-3-1b', messages=[])" \
  "no grant for 'gemma-3-1b'"
check "user agent may not read a system skill"     deny \
  "load('$SHELL_M')._conn.call('skill', name='manage-runner')" "system is below user"
check "user agent reads its own level"             allow \
  "load('$SHELL_M')._conn.call('skill', name='explain-error')"
check "app agent reads a user-level skill"         allow \
  "load('$EXPERT_M')._conn.call('skill', name='explain-error')"
check "app agent may not read a system skill"      deny \
  "load('$EXPERT_M')._conn.call('skill', name='manage-runner')" "system is below app"
check "ungranted model is refused by name"         deny \
  "load('$EXPERT_M').model('qwen3.5-0.8b')"         "no grant for model 'qwen3.5-0.8b'"
check "granted model resolves"                     allow \
  "load('$EXPERT_M').model('gemma-3-1b')"
check "app agent may not call back down to user"   deny \
  "load('$EXPERT_M')._conn.call('task', to='user/shell', skill='x', input=None)" \
  "a app agent may not call a user agent"
check "a denial does not reveal liveness"          deny \
  "load('$EXPERT_M')._conn.call('task', to='user/shell', skill='x', input=None)" \
  "may not call"
check "status is a system operation"               deny \
  "load('$SHELL_M')._conn.call('status')"           "system operation"

# A stub standing in for app/shell-expert, so routing can be tested without a
# model in the path. It registers by name; the policy that applies is the one
# on disk.
$PY -c "
import sys; sys.path.insert(0,'agents/lib')
from ainix_agent import Agent
a = Agent.from_manifest('$EXPERT_M')
while True:
    t = a.next_task()
    if t is None: break
    a.reply(t, {'command': 'echo stub', 'mutates': False})
" 2>/dev/null &
STUB=$!
sleep 0.8

echo
echo "routing"
check "listed peer routes end to end"              allow \
  "assert load('$SHELL_M').peer('app/shell-expert').task('shell.ask','hi',timeout=10)['command']=='echo stub'"
check "a live name cannot be taken over"           deny \
  "load('$EXPERT_M')"                                "already registered by another connection"
check "nobody may answer a task sent to another"   deny \
  "load('$SHELL_M')._conn.call('reply', task_id='t1', output='forged')" "no such task for you"

kill $STUB 2>/dev/null; wait $STUB 2>/dev/null; STUB=
sleep 0.5
check "a dead agent is not running, not hanging"   deny \
  "load('$SHELL_M').peer('app/shell-expert').task('shell.ask','hi',timeout=5)" "is not running"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
