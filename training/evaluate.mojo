# Held-out validation of a fine-tuned adapter.
#
# Mojo owns the entrypoint; the body is Python because evaluation is CSV, JSON,
# subprocess and an MLX model — three of which Mojo's stdlib does not cover.
# See docs/FINDINGS.md.

from std.python import Python


def main() raises:
    Python.add_to_path("training")
    var ev = Python.import_module("evaluate")
    _ = ev.main()
