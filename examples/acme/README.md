# ACME — a company as a tree of agents

A worked example: one company, four groups, ten agents, and a document store
nobody can read past their clearance. Everything here validates against the
same rules the distribution enforces on itself.

```bash
python3 ../../scripts/check_agent.py .     # 10 agents, 0 errors
```

## The org

```
ACME
├── marketing        clearance: internal
│   ├── social-media       LinkedIn and X posts, in ACME's voice
│   └── article-scout      finds outside articles worth sharing
├── web              clearance: internal
│   ├── web-content        the words on acme.com
│   └── web-posts          long-form posts, in step with social
├── strategy         clearance: confidential
│   ├── competitors        what rivals ship, price, and claim
│   ├── product-features   what to build next, and what not to
│   └── market             sizing, and where demand is moving
└── documents        clearance: restricted
    ├── librarian          custody of every document; brokers every read
    └── memory             what ACME learned, so it is not researched twice

user/console                the surface a person types into — no model, no clearance
```

## Clearance belongs to a group, not an agent

```toml
# groups.toml
[groups.marketing]
clearance = "internal"

# agents/app/social-media/agent.toml
[documents]
clearance = "internal"      # at most what marketing may hold
```

`public < internal < confidential < restricted`. An agent may hold **at most**
its group's level, and the validator enforces it:

```
error: app/social-media: clearance 'confidential' is above what group
       'marketing' may hold ('internal')
```

The ordering is deliberate. A group is an organisational fact — reviewed by a
human, changed rarely. Agents are added weekly. If clearance were per-agent
only, every new agent would be a fresh chance to quietly grant too much, and
the review that catches it happens in the busiest place.

**A user agent holds no clearance at all**, the same way it holds no model
grant:

```
error: user/console: user agents may not hold clearance above 'public' —
       route through an app agent, the same way they route model access
```

The human at the console may personally be cleared for anything. The console
is not, because the console is what an attacker reaches first.

## Three things the layout is doing on purpose

**`article-scout` is the least privileged agent in the company.** It reads the
open internet all day, so it holds `public` and no write tools. Its skill says
plainly that article text is data and never instruction — a page saying
"ignore previous instructions" is scored low and reported, not obeyed. Giving
the agent that eats untrusted pages access to ACME's documents would put the
whole store one prompt injection away from a third-party blog.

**`social-media` cannot see confidential work.** It writes what ACME says in
public and holds `internal`, so an unreleased feature cannot reach a draft post
by accident. It also cannot publish: it returns a draft and a proposed time,
and the posting tool is gated on a human. An agent that can publish without
review is a brand incident waiting for a bad sample.

**`librarian` is to documents what `agentd` is to models.** It holds the store
and brokers every read against the requester's clearance; no other agent opens
a document directly. Same principle: the thing that enforces access is the only
thing holding the addresses.

## What is deliberately absent

No agent has a tool it does not use. No agent lists a peer it never calls.
`product-features` is the only agent granted a frontier model, and that entry
ships `enabled = false` — reaching for the expensive option should be a
decision someone makes, not a default that quietly bills.

## Adapting it

Change `groups.toml` first — it is the shape of the company. Then give each
agent the lowest clearance that lets it do its job, and let the validator
argue with you about the rest.
