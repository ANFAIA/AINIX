# distill-dataset

## Procedure

1. **Start from prompts that have a known-good answer.** Without a reference
   there is nothing to verify against, and the pipeline degrades to trusting
   whatever the teacher said. NL2Bash's train split gives 40,636 of them.
2. **Exclude contamination once, at the source.** Drop any prompt that appears
   in the evaluation split or already in the training data. Doing this at
   generation time is the only place it can be done honestly.
3. **Never show a teacher the reference.** That is copying, not distillation,
   and it produces a dataset that measures nothing.
4. Ask several teachers of **different families** — disagreement is signal.
   Free OpenRouter models make this nearly free: `minimax/minimax-m3:free`
   carries the run; others contribute when they are not rate-limited.
5. **Gate on effect-equivalence**, not on plausibility. See
   [[verify-command]].
6. **Keep the hard prompts.** When no teacher matches the reference, write the
   reference command as the answer with the best teacher's explanation
   attached — correct by construction. Dropping them biases the dataset toward
   what teachers already know, which is the opposite of the point.
7. Record `origin` on every record (`equivalent` or `reference-anchored`) so a
   later pass can weight or drop them without guessing.

## Expect rate limits

Free-tier teachers return 429 constantly. Retry with backoff and keep going —
a run that dies on the first 429 wastes everything generated so far. Write
results incrementally and flush.

## Watch for

A single teacher carrying the whole run. If one model produces nearly all the
kept records, the "ensemble" is one model with extra latency — check the
`teacher` field distribution before claiming diversity.
