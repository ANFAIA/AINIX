# Have a model author an agent tree, then hold it to the validator.
#
# Mojo owns the entrypoint; the body is Python because this is JSON, HTTP and
# file writing — see docs/FINDINGS.md for what Mojo's stdlib does not yet cover.

from std.python import Python


def main() raises:
    Python.add_to_path("scripts")
    var gen = Python.import_module("generate_org")
    _ = gen.main()
