r"""Write one step's `run:` body out of an action or workflow YAML, verbatim.

README's published evidence is a shell body executed as written, so the body has
to come out of the YAML rather than be retyped into a scratch file. PyYAML is
not a dependency of this package and this script does not want it: a `run: |`
literal block is found by indentation alone, which is the same rule
tests/test_fence_publication.py uses when it checks that every such body sets
the shell's ballot options.

Usage: python tools/step_body.py YAML STEP_KEY OUT
STEP_KEY matches a step's `name:` or its `id:`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _keys(line: str) -> list[str]:
    stripped = line.strip().removeprefix("- ")
    return [
        stripped.removeprefix(prefix)
        for prefix in ("name: ", "id: ")
        if stripped.startswith(prefix)
    ]


def _entry_line(lines: list[str], i: int) -> int:
    """Index of the `- ` line opening the step that contains line `i`.

    A step is keyed by its `name:`, which is on the dash line itself, or by its
    `id:`, which is one level in. Both have to find the same block.
    """
    for k in range(i, -1, -1):
        if _indent(lines[k]) <= _indent(lines[i]) and lines[k].strip().startswith("- "):
            return k
    return i


def _step_block(lines: list[str], start: int) -> list[str]:
    """The entry line at `start` plus every line indented inside it."""
    block = [lines[start]]
    for following in lines[start + 1 :]:
        if following.strip() and _indent(following) <= _indent(lines[start]):
            break
        block.append(following)
    return block


def step_run_body(lines: list[str], key: str) -> str | None:
    """The literal `run: |` block belonging to the step keyed by `key`."""
    for i, line in enumerate(lines):
        if key not in _keys(line):
            continue
        entry = _entry_line(lines, i)
        block = _step_block(lines, entry)
        for offset, block_line in enumerate(block):
            if not block_line.strip().startswith("run: |"):
                continue
            return _dedent(_indented_body(lines, entry + offset, _indent(block_line)))
    return None


def _indented_body(lines: list[str], start: int, width: int) -> list[str]:
    """Every line after `start` that sits deeper than `width`."""
    body = []
    for following in lines[start + 1 :]:
        if following.strip() and _indent(following) <= width:
            break
        body.append(following)
    return body


def _dedent(body: list[str]) -> str:
    """Strip the block's own indentation, keeping the body's internal shape."""
    widths = [_indent(ln) for ln in body if ln.strip()]
    margin = min(widths) if widths else 0
    return "\n".join(ln[margin:] if ln.strip() else "" for ln in body).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: step_body.py YAML STEP_KEY OUT", file=sys.stderr)
        return 2
    path, key, out = argv[1:4]
    body = step_run_body(Path(path).read_text().splitlines(), key)
    if body is None:
        print(f"no run: | block for step {key!r} in {path}", file=sys.stderr)
        return 1
    Path(out).write_text(body)
    print(f"wrote {out}: {len(body.encode())} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
