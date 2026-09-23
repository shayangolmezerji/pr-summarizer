"""Unified-diff parsing, stdlib only.

The input is diff text as `git diff` writes it. No working tree is read and no
external diff library is used, so the tool runs anywhere a diff can be piped:
the CI runner, someone's shell, or the GitHub Action. The consequence of
hand-rolling the parser is recorded in docs/adr/0001-ast-before-model.md.

A FileChange carries enough per-line numbering to reconstruct, for the new side
of a file, every region the diff actually shows (context plus added lines). It
does not claim to reproduce lines the diff elided; the AST stage works on the
regions that are present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DIFF_GIT = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_NEW_FILE = re.compile(r"^new file mode (\d+)$")
_DELETED_FILE = re.compile(r"^deleted file mode (\d+)$")
_OLD_MODE = re.compile(r"^old mode (\d+)$")
_NEW_MODE = re.compile(r"^new mode (\d+)$")
_RENAME_FROM = re.compile(r"^rename from (.+)$")
_RENAME_TO = re.compile(r"^rename to (.+)$")
_SIMILARITY = re.compile(r"^similarity index (\d+)%$")
_BINARY = re.compile(r"^Binary files .* differ$")

ADDED = "added"
DELETED = "deleted"
RENAMED = "renamed"
MODIFIED = "modified"
MODE = "mode"


@dataclass
class Line:
    """One body line of a hunk, with its old and new file numbering.

    A line missing from one side (an addition has no old number, a deletion no
    new number) records None there, which is what lets reconstruction skip it.
    """

    kind: str  # ' ', '+', '-' or '\' (the no-newline marker)
    text: str
    old_no: int | None
    new_no: int | None


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[Line] = field(default_factory=list)

    def new_region(self) -> list[tuple[int, str]]:
        """(line number, text) for every new-side line this hunk shows."""
        return [(ln.new_no, ln.text) for ln in self.lines if ln.new_no is not None]

    def old_region(self) -> list[tuple[int, str]]:
        return [(ln.old_no, ln.text) for ln in self.lines if ln.old_no is not None]

    def added_count(self) -> int:
        return sum(1 for ln in self.lines if ln.kind == "+")

    def removed_count(self) -> int:
        return sum(1 for ln in self.lines if ln.kind == "-")


@dataclass
class FileChange:
    old_path: str
    new_path: str
    change_type: str
    hunks: list[Hunk] = field(default_factory=list)
    new_mode: str | None = None
    old_mode: str | None = None
    similarity: int | None = None
    binary: bool = False

    @property
    def path(self) -> str:
        return self.new_path if self.new_path != "/dev/null" else self.old_path

    def is_python(self) -> bool:
        return self.path.endswith(".py")

    def new_lines(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for h in self.hunks:
            out.extend(h.new_region())
        return out

    def old_lines(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for h in self.hunks:
            out.extend(h.old_region())
        return out

    def added(self) -> int:
        return sum(h.added_count() for h in self.hunks)

    def removed(self) -> int:
        return sum(h.removed_count() for h in self.hunks)


def parse(text: str) -> list[FileChange]:
    """Parse unified diff text into one FileChange per touched file.

    Tolerates the git extensions that carry the interesting metadata (rename,
    mode, similarity, binary) and the trailing "\\ No newline at end of file"
    marker, which has no line numbers of its own.
    """
    files: list[FileChange] = []
    cur: FileChange | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0
    old_left = new_left = 0
    # The split is on "\n" only, not splitlines(): CRLF diffs carry the "\r"
    # as part of the line's content, and splitting on it would erase the very
    # marker the AST stage has to normalize.
    for raw in text.split("\n"):
        m = _DIFF_GIT.match(raw)
        if m:
            cur = FileChange(old_path=m.group(1), new_path=m.group(2), change_type=MODIFIED)
            files.append(cur)
            hunk = None
            continue

        if cur is None:
            # Anything before the first `diff --git` (a commit message from
            # `git format-patch`, a stray banner) is not a file header.
            continue

        if (mo := _NEW_FILE.match(raw)):
            cur.new_mode = mo.group(1)
            cur.change_type = ADDED
            continue
        if mo := _DELETED_FILE.match(raw):
            cur.old_mode = mo.group(1)
            cur.change_type = DELETED
            continue
        if mo := _OLD_MODE.match(raw):
            cur.old_mode = mo.group(1)
            continue
        if mo := _NEW_MODE.match(raw):
            cur.new_mode = mo.group(1)
            continue
        if mo := _SIMILARITY.match(raw):
            cur.similarity = int(mo.group(1))
            continue
        if mo := _RENAME_FROM.match(raw):
            cur.old_path = mo.group(1)
            cur.change_type = RENAMED
            continue
        if mo := _RENAME_TO.match(raw):
            cur.new_path = mo.group(1)
            cur.change_type = RENAMED
            continue
        if _BINARY.match(raw):
            cur.binary = True
            hunk = None
            continue

        if raw.startswith("--- ") or raw.startswith("+++ "):
            if hunk is None:  # a header only precedes the first hunk of a file
                p = _strip_prefix(raw[4:])
                if raw[0] == "-":
                    cur.old_path = p
                else:
                    cur.new_path = p
            continue

        if mo := _HUNK.match(raw):
            old_no = int(mo.group(1))
            new_no = int(mo.group(3))
            old_left = int(mo.group(2)) if mo.group(2) is not None else 1
            new_left = int(mo.group(4)) if mo.group(4) is not None else 1
            hunk = Hunk(
                old_start=old_no,
                old_count=old_left,
                new_start=new_no,
                new_count=new_left,
                header=mo.group(5).strip(),
            )
            cur.hunks.append(hunk)
            continue

        if hunk is None:
            # Mode-only and pure-rename blocks sit here with no hunk yet.
            continue

        kind, body = _classify(raw)
        if kind == "\\":
            # The no-newline marker annotates the previous line; it is not a
            # line of the file, so it gets no numbering and consumes no count.
            hunk.lines.append(Line("\\", body, None, None))
            continue

        # A hunk is done once its declared old and new line counts are used up.
        # Anything after that is a boundary, not another body line: this is what
        # stops a diff whose final line has no newline from pulling the next
        # file's "index ..." header into the last hunk.
        in_old = kind in (" ", "-") and old_left > 0
        in_new = kind in (" ", "+") and new_left > 0
        if not (in_old or in_new):
            hunk = None
            continue

        line = Line(kind, body, None, None)
        if in_new:
            line.new_no = new_no
            new_no += 1
            new_left -= 1
        if in_old:
            line.old_no = old_no
            old_no += 1
            old_left -= 1
        hunk.lines.append(line)

    for cur in files:
        if cur.change_type == MODIFIED and not cur.hunks and cur.old_mode and cur.new_mode:
            # A mode change with no content hunks is not a modification.
            cur.change_type = MODE

    return files


def _classify(raw: str) -> tuple[str, str]:
    if not raw:
        return " ", ""  # an empty context line, sent without its leading space
    return raw[0], raw[1:]


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path
