# verify-command

## Procedure

1. **Exit status is not correctness.** `sort -r` and `sort -rn` both exit 0
   and only one answers the question. Checking that a command *runs* measures
   whether it is well-formed, never whether it is right.
2. Compare **effects**. Run the candidate and a known-good reference in
   identical, freshly seeded containers, and compare what each prints and what
   each leaves on disk. `training/reward.py` does this.
3. **Hash stdout verbatim.** Sorting it before hashing scores
   `ls /var/log | sort -r` equivalent to `ls -S /var/log | head -20` — the
   exact pair the check exists to separate. Ordering *is* the answer for half
   of these questions.
4. Grade, do not filter: `1.0` equivalent, `0.6` ran cleanly with a different
   effect, `0.0` broken. Rejection sampling needs to rank; a 0.6 that outranks
   a 0.0 still carries signal.
5. **Batch the probes.** Container startup dominates — re-seed the fixture
   between commands inside one container (`probe_many`, 40 at a time). Scoring
   a few hundred candidates one container at a time turns minutes into an hour.

## With no reference

Fall back to "did it run", and **say so in the verdict**. An unlabelled weak
check that looks like a strong one is worse than no check.

## Never

Do not run a candidate outside the sandbox, and keep the hard-refuse list
(`rm -rf /`, `mkfs`, fork bombs, writes to raw devices) ahead of execution —
a throwaway container is still a real kernel.
