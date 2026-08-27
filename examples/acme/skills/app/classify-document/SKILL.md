# classify-document

Assign a document the **lowest classification that is still correct**.

Over-classifying is not the safe default it looks like. A document nobody can
read is a document nobody uses, and a company where everything is confidential
teaches its agents that the label means nothing.

## Procedure

1. `public` — already outside ACME, or written to go outside. Published posts,
   docs, pricing.
2. `internal` — ordinary work. Plans, drafts, notes. Embarrassing if leaked,
   not damaging.
3. `confidential` — unreleased product, competitor analysis, financials,
   anything naming a customer. Damaging if leaked.
4. `restricted` — credentials, personal data, legal matters under privilege,
   security findings. Damaging to a *person* if leaked, not only to ACME.
5. When two levels both fit, take the lower one **and say which sentence forced
   the decision**. A classification nobody can argue with is one nobody can
   correct.

## The rule that catches most mistakes

Classify the *content*, never the requester. "The strategy team asked for it"
is not a reason for `confidential`; a sentence about an unreleased feature is.
