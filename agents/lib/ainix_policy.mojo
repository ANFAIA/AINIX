# The broker's decisions, in Mojo.
#
# Every allow and deny agentd makes reduces to one of these predicates: is this
# a legal name, may this tier call that one, may this tier see that skill level,
# does this clearance cover that classification, what level does an unlabelled
# document get. They are pure — no I/O, no registry — so they are the part of
# the broker that belongs in Mojo first. agentd imports this module when it is
# built and falls back to agents/lib/policy_py.py when it is not (the image has
# no Mojo toolchain yet); test/policy-parity.py checks both give the same answer
# for every input it can enumerate.
#
#   mojo build --emit shared-lib agents/lib/ainix_policy.mojo -o agents/lib/ainix_policy.so

from std.os import abort
from std.python import Python, PythonObject
from std.python.bindings import PythonModuleBuilder


def _tier_index(tier: String) -> Int:
    """Order of privilege: user (top, least) = 0, app = 1, system = 2."""
    if tier == "user":
        return 0
    if tier == "app":
        return 1
    if tier == "system":
        return 2
    return -1


def _valid_name(name: String) -> Bool:
    """[a-z0-9][a-z0-9-]{0,63}, checked byte by byte: Mojo's stdlib has no
    regex, and this is the one check that stands between a request and a
    filesystem path."""
    var n = name.byte_length()
    if n == 0 or n > 64:
        return False
    var bytes = name.as_bytes()
    for i in range(n):
        var c = Int(bytes[i])
        var lower = c >= ord("a") and c <= ord("z")
        var digit = c >= ord("0") and c <= ord("9")
        if lower or digit:
            continue
        if c == ord("-") and i > 0:
            continue
        return False
    return True


def valid_name(name: PythonObject) raises -> PythonObject:
    return PythonObject(_valid_name(String(py=name)))


def tier_may_call(caller: PythonObject, callee: PythonObject) raises -> PythonObject:
    """Tiers: user -> app; app -> app; system -> anything. Nothing calls down into a
    user agent except system."""
    var a = String(py=caller)
    var b = String(py=callee)
    if _tier_index(a) < 0 or _tier_index(b) < 0:
        return PythonObject(False)
    if a == "system":
        return PythonObject(True)
    return PythonObject(b == "app")


def tier_sees_level(tier: PythonObject, level: PythonObject) raises -> PythonObject:
    """A tier sees its own skill level and every level above it (user is the
    top), never below."""
    var t = _tier_index(String(py=tier))
    var l = _tier_index(String(py=level))
    if t < 0 or l < 0:
        return PythonObject(False)
    return PythonObject(l <= t)


def clearance_covers(
    clearance: PythonObject, level: PythonObject, order: PythonObject
) raises -> PythonObject:
    """Read at or below your own clearance. An unknown clearance or level
    covers nothing."""
    var c = String(py=clearance)
    var d = String(py=level)
    var ci = -1
    var di = -1
    var i = 0
    for item in order:
        var s = String(py=item)
        if s == c:
            ci = i
        if s == d:
            di = i
        i += 1
    if ci < 0 or di < 0:
        return PythonObject(False)
    return PythonObject(di <= ci)


def classify(label: PythonObject, order: PythonObject) raises -> PythonObject:
    """The level a document is served at. Fail closed: no label, or a label
    this deployment does not have, means the highest level. With no levels at
    all, there is no classification and everything is public."""
    var n = Int(py=order.__len__())
    if n == 0:
        return PythonObject("public")
    var top = order[n - 1]
    if label is None:
        return top
    var l = String(py=label)
    for item in order:
        if String(py=item) == l:
            return item
    return top


def clamp(value: PythonObject, lo: PythonObject, hi: PythonObject) raises -> PythonObject:
    """Bound a caller-supplied number — max_tokens, a task timeout."""
    var v = Float64(py=value)
    var a = Float64(py=lo)
    var b = Float64(py=hi)
    if v < a:
        return lo
    if v > b:
        return hi
    return value


def engine() raises -> PythonObject:
    return PythonObject("mojo")


@export
def PyInit_ainix_policy() abi("C") -> PythonObject:
    try:
        var m = PythonModuleBuilder("ainix_policy")
        m.def_function[valid_name]("valid_name")
        m.def_function[tier_may_call]("tier_may_call")
        m.def_function[tier_sees_level]("tier_sees_level")
        m.def_function[clearance_covers]("clearance_covers")
        m.def_function[classify]("classify")
        m.def_function[clamp]("clamp")
        m.def_function[engine]("engine")
        return m.finalize()
    except e:
        abort(String("failed to create ainix_policy: ", e))
