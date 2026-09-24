"""The same predicates as ainix_policy.mojo, for where Mojo is not built.

Kept deliberately line-for-line with the Mojo module; test/policy-parity.py
enumerates inputs and fails on any disagreement. If you change a rule, change
it in both, and the parity test tells you if you did not.
"""

_TIERS = {"user": 0, "app": 1, "system": 2}


def valid_name(name) -> bool:
    if not isinstance(name, str) or not 0 < len(name.encode()) <= 64:
        return False
    for i, ch in enumerate(name):
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            continue
        if ch == "-" and i > 0:
            continue
        return False
    return True


def tier_may_call(caller, callee) -> bool:
    if caller not in _TIERS or callee not in _TIERS:
        return False
    return True if caller == "system" else callee == "app"


def tier_sees_level(tier, level) -> bool:
    if tier not in _TIERS or level not in _TIERS:
        return False
    return _TIERS[level] <= _TIERS[tier]


def clearance_covers(clearance, level, order) -> bool:
    order = list(order)
    if clearance not in order or level not in order:
        return False
    return order.index(level) <= order.index(clearance)


def classify(label, order):
    order = list(order)
    if not order:
        return "public"
    return label if label in order else order[-1]


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


def engine() -> str:
    return "python"
