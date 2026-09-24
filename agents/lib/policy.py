"""Which implementation of the broker's decisions is in force.

Mojo first: the compiled ainix_policy module when it can be imported, the
Python twin otherwise. AINIX_POLICY=mojo makes the Mojo module mandatory — a
deployment that meant to run Mojo should fail at start, not quietly run
Python — and AINIX_POLICY=python forces the twin.
"""
import os

_want = os.environ.get("AINIX_POLICY", "auto")

if _want == "python":
    import policy_py as impl
else:
    try:
        import ainix_policy as impl
    except ImportError:
        if _want == "mojo":
            raise
        import policy_py as impl

valid_name = impl.valid_name
tier_may_call = impl.tier_may_call
tier_sees_level = impl.tier_sees_level
clearance_covers = impl.clearance_covers
classify = impl.classify
clamp = impl.clamp
ENGINE = str(impl.engine())
