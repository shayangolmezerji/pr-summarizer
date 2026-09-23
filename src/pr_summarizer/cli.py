"""Command line: diff in, structural brief out, optional model summary.

Subcommand-free on purpose; the only real choice is where the diff comes from
and how the result is formatted. The library never prints, so every byte of user
output is written here and is easy to reason about in tests.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

from . import brief as brief_mod
from . import model

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MODEL = 3

FORMATS = ("text", "json")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pr-summarizer",
        description="Turn a pull-request diff into a structural summary of what "
        "changed about the code's shape.",
    )
    p.add_argument(
        "path",
        nargs="?",
        help="A .diff/.patch file. Omit to read the diff from stdin.",
    )
    p.add_argument(
        "--git",
        nargs="+",
        metavar="ARG",
        help="Produce the diff with `git diff ARG...` instead of reading one.",
    )
    p.add_argument("--format", choices=FORMATS, default="text", help="Brief format.")
    p.add_argument(
        "--no-model",
        action="store_true",
        help="Never contact a model; print only the structural brief.",
    )
    p.add_argument(
        "--max-context",
        type=int,
        default=None,
        metavar="BYTES",
        help="Byte budget for the brief sent to the model. A byte count, not "
        "a token count; the structural brief is usually well under any budget.",
    )
    return p


def _read_diff(args: argparse.Namespace) -> str:
    if args.git:
        # argv list, never a shell string: git arguments cannot break out into
        # commands here.
        proc = subprocess.run(
            ["git", "diff", *args.git],
            capture_output=True,
            check=True,
        )
        return proc.stdout.decode("utf-8", errors="replace")
    if args.path:
        # read_bytes, not open().read(): universal-newline mode would strip the
        # "\\r" a CRLF diff carries as content.
        return open(args.path, "rb").read().decode("utf-8", errors="replace")
    return sys.stdin.buffer.read().decode("utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        diff_text = _read_diff(args)
    except subprocess.CalledProcessError as exc:
        print(f"git diff failed: {exc.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print(f"cannot read the diff: {exc}", file=sys.stderr)
        return EXIT_USAGE

    parsed = brief_mod.build(diff_text)

    summary: str | None = None
    if not args.no_model:
        try:
            summary = model.summarize(
                brief_mod.render_text(parsed),
                max_bytes=args.max_context,
            )
        except model.NotConfiguredError as exc:
            print(f"model skipped ({exc}); showing the structural brief alone", file=sys.stderr)
        except model.ModelError as exc:
            print(f"model error: {exc}", file=sys.stderr)
            return EXIT_MODEL

    if args.format == "json":
        sys.stdout.write(brief_mod.render_json(parsed, summary=summary))
    else:
        sys.stdout.write(brief_mod.render_text(parsed))
        if summary:
            print("\nmodel summary\n" + "-" * 40)
            print(summary)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
