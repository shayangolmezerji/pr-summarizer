r"""Write the patch behind README's published fence evidence.

Not part of the package, and deliberately not in `tests/fixtures/`: that
directory is the literal byte output of `git diff`, and this is not. `git diff`
ends its header lines with LF, so a patch whose headers carry CR arrives only as
a fetched or hand-built patch, which is what this script is for. The name of the
one file it touches is three backticks, and `diff.py` keeps a carriage return as
part of a line rather than as a line ending, so the brief renders that run alone
on a line.

Usage: python tools/hostile_patch.py PATH
"""

from __future__ import annotations

import sys
from pathlib import Path

# A raw string: the name is three backticks and nothing here needs escaping.
NAME = r"```"

LINES = [
    f"diff --git a/{NAME} b/{NAME}",
    "index 0000000..1111111 100644",
    f"--- a/{NAME}",
    f"+++ b/{NAME}",
    "@@ -0,0 +1 @@",
    "+x = 1",
]


def patch() -> bytes:
    """The whole patch, header lines and all, CRLF terminated."""
    return ("\r\n".join(LINES) + "\r\n").encode()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: hostile_patch.py PATH", file=sys.stderr)
        return 2
    data = patch()
    Path(argv[1]).write_bytes(data)
    print(f"wrote {argv[1]}: {len(data)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
