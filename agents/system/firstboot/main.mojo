# First-boot setup. Runs once, before any other agent, on the console.
#
# Order matters and is deliberate: connectivity first, because every later
# question ("which model do you want?") is meaningless without it, and because
# a machine with no network must still reach a usable shell.
#
# The interactive body is Python behind interop — see docs/FINDINGS.md for the
# Mojo-first policy and what is still on the Python side.

from std.python import Python


def main() raises:
    Python.add_to_path(".")
    var firstboot = Python.import_module("firstboot")
    _ = firstboot.run()
