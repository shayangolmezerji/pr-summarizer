r"""Count the lines of a markdown body that can close an open code fence.

One line convention, and it is CommonMark's: a line ends at CRLF, at LF, or at a
lone carriage return. That is the only convention under which "which line closes
this fence" has an answer, because a bare run of backticks followed by a CR is
exactly the shape that question is about. `wc -l` counts LF endings only, so on a
body carrying a lone carriage return it reports fewer lines than this script does,
and the two numbers are not comparable.

Inside a fenced block CommonMark parses nothing else, so the only line that can
close the block is a run of three or more backticks with at most three spaces
before it and nothing but spaces after it. A body whose only such line is the one
the writer of the fence intended cannot be closed from inside.

Usage: python tools/count_fence_lines.py PATH
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# CommonMark's own definition of a line ending, which is what splits the body.
LINE_END = re.compile(r"\r\n|\r|\n")
CLOSER = re.compile(r" {0,3}`{3,} *")


def commonmark_lines(text: str) -> list[str]:
    """The body split the way CommonMark splits it.

    A trailing line ending closes the line before it and does not open another
    one, so `split` alone would report one more line than the document has.
    """
    parts = LINE_END.split(text)
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def closer_lines(text: str) -> list[int]:
    """1-based numbers of the CommonMark lines that would close an open fence."""
    return [i for i, line in enumerate(commonmark_lines(text), 1) if CLOSER.fullmatch(line)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: count_fence_lines.py PATH", file=sys.stderr)
        return 2
    raw = Path(argv[1]).read_bytes()
    text = raw.decode()
    print(f"bytes: {len(raw)}")
    print(f"CommonMark lines: {len(commonmark_lines(text))}")
    print(f"lines that can close a fence: {closer_lines(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
