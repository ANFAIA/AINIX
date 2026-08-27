# Globex — an agent tree a model designed

Not hand-written. `scripts/generate_org.py` gave MiniMax M3 the AINIX manifest
contract and [the brief](../orgs/globex.md), and this is what came back —
14 agents, 8 groups, 14 skills.

```bash
python3 ../../scripts/generate_org.py --brief examples/orgs/globex.md --out examples/globex
python3 ../../scripts/check_agent.py .      # 14 agents, 0 errors
```

## What it produced

| tier | group | agent | clearance |
|---|---|---|---|
| user | console | console | public |
| app | support | bug-intake, ticket-responder, help-article-drafter | **public** |
| app | revenue | lead-qualifier, sequence-drafter | internal |
| app | finance | invoice-clerk, renewal-forecaster | confidential |
| app | people | recruiter | confidential |
| app | engineering | bug-triager, dependency-reviewer, release-noter | restricted |
| app | knowledge | knowledge-broker | restricted |
| system | kernel | supervisor | internal |

## The part worth looking at

**It put all three support agents at `public`.** The brief said support reads
untrusted customer input; the contract said an agent that reads untrusted
content must hold the lowest clearance. It connected those and gave the
customer-facing function the least privilege in the company — which is the
whole point of the design and the thing that is easy to get backwards.

It also gave `knowledge-broker` eleven peers and everyone else two or three,
arriving at the hub-and-spoke shape that document custody implies without
being told to.

## What it got wrong

**Peer references, every time.** The first run wrote `knowledge.broker` and
bare `sales-assistant` instead of `app/knowledge-broker` — 16 errors, all the
same class. Tightening the contract to spell out `<tier>/<name>` fixed most of
it; `normalise_peers()` repairs the mechanical remainder and prints each repair,
leaving anything that resolves to nothing broken for the validator to reject.
Inventing an edge the design did not ask for would be worse than a failed check.

**One design mistake it could not have caught itself.** It wrote
`route-request` as an app-level skill and granted it to the user console:

```
error: user/console: skill 'route-request' is at level 'app', which a user
       agent cannot see
```

Routing a human's request is the console's own work, so the fix was to move the
skill down to `user`, not to widen what the console can see. That distinction —
lower the thing, do not raise the requester — is the sort of judgement the
validator can force but not make.

## What this is evidence for

An org chart in English became a structure a validator argues with. The model
got the shape right and the syntax wrong, which is the good failure mode: wrong
syntax is caught in a second, while a plausible-looking over-grant would have
survived review. The check is what makes generation usable, not the generation.
