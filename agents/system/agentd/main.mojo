# agentd — the system agent every other agent depends on.
#
# Mojo owns the process and the control flow. The broker body is Python behind
# interop because agentd is entirely JSON, sockets and HTTP, and Mojo's stdlib
# has none of those three (see docs/FINDINGS.md). When they land, the body
# moves up without the entrypoint changing.

from std.python import Python
from std.os import getenv


def main() raises:
    # In Mojo 1.0 getenv returns a String with a default, not an Optional —
    # the modular/skills interop guide says otherwise, and the compiler wins.
    Python.add_to_path(getenv("AINIX_AGENTD_DIR", "."))

    var agentd = Python.import_module("agentd")
    var asyncio = Python.import_module("asyncio")
    _ = asyncio.run(agentd.main())
