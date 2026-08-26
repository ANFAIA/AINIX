# agentd — the system agent every other agent depends on.
#
# Mojo owns the process and the control flow. The broker body is Python behind
# interop because agentd is entirely JSON, sockets and HTTP, and Mojo's stdlib
# has none of those three (see docs/FINDINGS.md). When they land, the body
# moves up without the entrypoint changing.

from std.python import Python
from std.os import getenv


def main() raises:
    var here = getenv("AINIX_AGENTD_DIR")
    Python.add_to_path(here.value() if here else ".")

    var agentd = Python.import_module("agentd")
    var asyncio = Python.import_module("asyncio")
    _ = asyncio.run(agentd.main())
