#!/usr/bin/env bash
# The negative tests matter more than the happy path: a capability system is
# only worth anything if it fails closed. Each case here is something an agent
# might plausibly try, and every one must be refused with a reason.
set -u
cd "$(dirname "$0")/.."

export AINIX_SOCK=${AINIX_SOCK:-/tmp/ainix-test-agentd.sock}
export AINIX_ROOT=$PWD
export PYTHONPATH=$PWD/agents/lib
PY=${PY:-/opt/homebrew/bin/python3}

$PY agents/system/agentd/agentd.py 2>/tmp/agentd.log &
AGENTD=$!
trap 'kill $AGENTD 2>/dev/null; rm -f "$AINIX_SOCK"' EXIT
for _ in $(seq 50); do [ -S "$AINIX_SOCK" ] && break; sleep 0.1; done

# A stub standing in for app/shell-expert, so routing can be tested without a
# model in the path. It registers with the real manifest — the policy under
# test is the manifest's, not the stub's.
$PY -c "
import sys; sys.path.insert(0,'agents/lib')
from ainix_agent import Agent
a = Agent.from_manifest('agents/app/shell-expert/agent.toml')
while True:
    t = a.next_task()
    if t is None: break
    a.reply(t, {'command': 'echo stub', 'mutates': False})
" 2>/dev/null &
STUB=$!
trap 'kill $AGENTD $STUB 2>/dev/null; rm -f "$AINIX_SOCK"' EXIT
sleep 0.6

pass=0; fail=0
check() { # check <name> <expect: allow|deny> <python expression>
  local name=$1 expect=$2 code=$3 out
  out=$($PY -c "
import sys, json, tomllib
sys.path.insert(0, 'agents/lib')
from ainix_agent import Agent, Conn, Denied
def load(p):
    a = Agent.__new__(Agent); a._conn = Conn()
    with open(p,'rb') as fh: a.manifest = tomllib.load(fh)
    a._conn.call('register', manifest=a.manifest)
    x = a.manifest['agent']; a.name=f\"{x['tier']}/{x['name']}\"; a.tier=x['tier']
    return a
try:
    $code
    print('ALLOW')
except Denied as e:
    print('DENY', e)
except Exception as e:
    print('ERROR', type(e).__name__, e)
" 2>/dev/null)
  local got=${out%% *}
  if { [ "$expect" = allow ] && [ "$got" = ALLOW ]; } || \
     { [ "$expect" = deny ]  && [ "$got" = DENY  ]; }; then
    printf '  \033[32mok\033[0m   %-46s %s\n' "$name" "${out#* }"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m %-46s expected %s, got: %s\n' "$name" "$expect" "$out"; fail=$((fail+1))
  fi
}

echo "capability enforcement"
check "user agent may not use a model"        deny \
  "load('agents/user/shell/agent.toml')._conn.call('infer', model='gemma-3-1b', messages=[])"
check "user agent may not read a system skill" deny \
  "load('agents/user/shell/agent.toml')._conn.call('skill', name='manage-runner')"
check "user agent reads its own level"         allow \
  "load('agents/user/shell/agent.toml')._conn.call('skill', name='explain-error')"
check "app agent reads a user-level skill"     allow \
  "load('agents/app/shell-expert/agent.toml')._conn.call('skill', name='explain-error')"
check "app agent may not read a system skill"  deny \
  "load('agents/app/shell-expert/agent.toml')._conn.call('skill', name='manage-runner')"
check "registered non-peer is refused"         deny \
  "load('agents/app/shell-expert/agent.toml')._conn.call('task', to='user/shell', skill='x', input=None)"
check "listed peer routes end to end"          allow \
  "assert load('agents/user/shell/agent.toml').peer('app/shell-expert').task('shell.ask','hi',timeout=10)['command']=='echo stub'"
check "ungranted model is refused by name"     deny \
  "load('agents/app/shell-expert/agent.toml').model('qwen3.5-0.8b')"
check "granted model resolves"                 allow \
  "load('agents/app/shell-expert/agent.toml').model('gemma-3-1b')"
check "unregistered connection is refused"     deny \
  "Conn().call('infer', model='gemma-3-1b', messages=[])"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
