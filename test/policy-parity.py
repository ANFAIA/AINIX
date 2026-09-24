"""The Mojo policy module and its Python twin must agree on every input.

Exhaustive over tiers, levels and clearance orders; a few thousand names
including every single byte and every pair from a hostile alphabet. Any
disagreement is printed and fails the run — two implementations of a security
rule that differ are two rules.
"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents/lib"))
import ainix_policy as mojo      # noqa: E402
import policy_py as py           # noqa: E402

assert str(mojo.engine()) == "mojo"
tiers = ["user", "app", "system", "", "root", "User", "app "]
orders = [[], ["public"], ["public", "internal", "confidential", "restricted"],
          ["low", "high"]]
labels = [None, "public", "internal", "confidential", "restricted", "secret", ""]

cases, bad = 0, []
def same(fn, *args):
    global cases
    cases += 1
    a, b = getattr(mojo, fn)(*args), getattr(py, fn)(*args)
    if a != b:
        bad.append((fn, args, a, b))

names = ["", "a", "-a", "a-", "shell-expert", "../system", "a/b", "A", "a.b",
         "x" * 64, "x" * 65, "é", "a\x00", "0", "9-z"]
alphabet = "az09-./_A \x00é"
names += ["".join(p) for p in itertools.product(alphabet, repeat=2)]
names += [chr(c) for c in range(256)]
for n in names:
    same("valid_name", n)
for a, b in itertools.product(tiers, repeat=2):
    same("tier_may_call", a, b)
    same("tier_sees_level", a, b)
for order in orders:
    for c, d in itertools.product(labels[1:] + ["x"], repeat=2):
        same("clearance_covers", c, d, order)
    for lab in labels:
        same("classify", lab, order)
for v, lo, hi in itertools.product([-5, 0, 1, 512, 4096, 10**9, 2.5], [1], [4096]):
    same("clamp", v, lo, hi)

for fn, args, a, b in bad[:20]:
    print(f"DISAGREE {fn}{args!r}: mojo={a!r} python={b!r}")
print(f"{cases} cases, {len(bad)} disagreements")
sys.exit(1 if bad else 0)
