"""The brief: one deterministic structure that both renderings read from.

A Brief is the whole product of the AST stage plus the cross-file view the diff
alone cannot give a reader: which helpers moved between files, which names were
renamed, which public signatures moved and how many times this diff calls them.
text and json are two views of this one object, so a terminal reader and a JSON
consumer can never be shown different changes.

The one asymmetry between them is deliberate. `render_text` defuses runs of
backticks, because its output is what the Action and the example workflow wrap in
a fenced block, and a backtick run that came out of the diff could close that
fence early and leave the rest of the brief rendering as markdown in a comment
authored by the bot. `render_json` carries the path it was given: `json.dumps`
turns a carriage return into `\\r`, so no line of it can be a fence, and a machine
consumer needs the real file name.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import ast_stage, diff
from .ast_stage import FileAnalysis, Symbol

# A run of backticks, however long: three of them are a fence and one or two are
# an inline-code span, and both kinds are the diff author's punctuation.
_BACKTICK_RUN = re.compile(r"`+")


def _defuse_backtick_runs(text: str) -> str:
    """Prefix every run of backticks with a backslash, once, over the whole body.

    Applied to the assembled text rather than to the path field alone so that
    nothing else the diff authored, an annotation's string literal or a
    decorator expression either, gets a live run into the fence. Inside a fenced
    block markdown does not un-escape, so a hostile path reads as a backslash and
    its backticks there: inert, and visibly altered rather than silently dropped.
    """
    return _BACKTICK_RUN.sub(r"\\\g<0>", text)


@dataclass
class SignatureChange:
    path: str
    qualname: str
    old: str
    new: str
    detail: ast_stage.SignatureDiff
    call_sites: int

    @property
    def public(self) -> bool:
        return not any(p.startswith("_") for p in self.qualname.split("."))


@dataclass
class Move:
    qualname: str
    frm: str
    to: str


@dataclass
class Rename:
    path: str
    frm: str
    to: str


@dataclass
class Brief:
    files: list[FileAnalysis] = field(default_factory=list)
    signature_changes: list[SignatureChange] = field(default_factory=list)
    moves: list[Move] = field(default_factory=list)
    renames: list[Rename] = field(default_factory=list)
    public_added: list[str] = field(default_factory=list)
    public_removed: list[str] = field(default_factory=list)
    risk: list[str] = field(default_factory=list)

    @property
    def files_changed(self) -> int:
        return len(self.files)

    @property
    def python_files(self) -> list[FileAnalysis]:
        return [f for f in self.files if f.python]


def build(diff_text: str) -> Brief:
    """Compute the brief for a unified diff. Pure function of the input text."""
    changes = diff.parse(diff_text)
    analyses = [ast_stage.analyze(c) for c in changes]
    brief = Brief(files=analyses)

    brief.signature_changes = _signature_changes(changes, analyses)
    brief.moves = _moves(analyses)
    brief.renames = _renames(analyses)

    moved = {(m.qualname, m.to) for m in brief.moves}
    moved_from = {(m.qualname, m.frm) for m in brief.moves}
    renamed_to = {(r.path, r.to) for r in brief.renames}
    renamed_from = {(r.path, r.frm) for r in brief.renames}
    for a in analyses:
        if a.untrusted or not a.parsed:
            continue
        d = a.deltas()
        for s in d["added"]:
            if (
                s.top_level
                and s.is_public
                and (s.qualname, a.path) not in moved
                and (a.path, s.qualname) not in renamed_to
            ):
                brief.public_added.append(f"{a.module}.{s.qualname}")
        # A rename or a move is the precise statement about this name; listing
        # it again as a bare removal would double-count one fact as two.
        for s in d["removed"]:
            if (
                s.top_level
                and s.is_public
                and (s.qualname, a.path) not in moved_from
                and (a.path, s.qualname) not in renamed_from
            ):
                brief.public_removed.append(f"{a.module}.{s.qualname}")

    brief.risk = _risk(brief)
    return brief


def _signature_changes(changes: list[diff.FileChange], analyses: list[FileAnalysis]):
    out: list[SignatureChange] = []
    for a in analyses:
        if a.untrusted or not a.parsed:
            continue
        for qual, new in sorted(a.symbols_new.items()):
            old = a.symbols_old.get(qual)
            if old is None:
                continue
            detail = ast_stage.signature_diff(old, new)
            if not detail.any:
                continue
            calls = sum(ast_stage.count_call_sites(c, new.name) for c in changes)
            out.append(
                SignatureChange(
                    path=a.path,
                    qualname=qual,
                    old=old.signature(),
                    new=new.signature(),
                    detail=detail,
                    call_sites=calls,
                )
            )
    return out


def _moves(analyses: list[FileAnalysis]) -> list[Move]:
    """A removed symbol reappearing, same shape, in another changed file.

    Only top-level names count: a method "moving" is really a class move, which
    is rarer and not claimed here.
    """
    removals = [
        (a, s)
        for a in analyses
        if a.parsed and not a.untrusted
        for s in a.deltas()["removed"]
        if s.top_level
    ]
    additions = [
        (a, s)
        for a in analyses
        if a.parsed and not a.untrusted
        for s in a.deltas()["added"]
        if s.top_level
    ]
    moves: list[Move] = []
    taken: set[tuple[str, str]] = set()
    for from_a, old in removals:
        for to_a, new in additions:
            if to_a.path == from_a.path or (to_a.path, new.qualname) in taken:
                continue
            if old.name == new.name and old.similar_to(new):
                moves.append(Move(old.qualname, from_a.path, to_a.path))
                taken.add((to_a.path, new.qualname))
                break
    return moves


def _renames(analyses: list[FileAnalysis]) -> list[Rename]:
    out: list[Rename] = []
    for a in analyses:
        if a.untrusted or not a.parsed:
            continue
        d = a.deltas()
        for old, new in ast_stage.detect_renames(d["removed"], d["added"]):
            out.append(Rename(a.path, old.name, new.name))
    return out


def _risk(brief: Brief) -> list[str]:
    lines: list[str] = []
    for sc in brief.signature_changes:
        n = sc.call_sites
        lines.append(
            f"signature of {sc.path}:{sc.qualname} changed; "
            f"{n} call site{'s' if n != 1 else ''} in this diff"
        )
    for m in brief.moves:
        lines.append(f"{m.qualname} moved {m.frm} -> {m.to}")
    for r in brief.renames:
        lines.append(f"{r.frm} renamed to {r.to} in {r.path} (inferred)")
    for a in brief.files:
        if a.untrusted:
            lines.append(f"{a.path} changed region does not parse; delta withheld")
        elif a.python and not a.parsed:
            lines.append(f"{a.path}: no structural analysis")
    return lines


# ------------------------------------------------------------------ rendering


def render_text(brief: Brief) -> str:
    out: list[str] = []
    out.append(f"structural brief: {brief.files_changed} file(s) changed")
    out.append("")
    for a in brief.files:
        out.append(f"{a.path}  [{a.change_type}]")
        if not a.python:
            out.append(
                f"  {a.lines_added + a.lines_removed} line(s) touched; "
                f"no structural analysis for this language"
            )
            continue
        if a.untrusted or not a.parsed:
            out.append(f"  {a.note or 'no structural analysis'}")
            _render_placements(out, a)
            continue
        _render_symbols(out, a, brief)
        _render_placements(out, a)
        out.append("")

    out.append("cross-file view")
    out.append(f"  public added:   {', '.join(brief.public_added) or 'none'}")
    out.append(f"  public removed: {', '.join(brief.public_removed) or 'none'}")
    out.append(f"  moves:          {_fmt_moves(brief) or 'none'}")
    out.append(f"  renames:        {_fmt_renames(brief) or 'none'}")
    out.append("")
    out.append("risk")
    if brief.risk:
        out.extend(f"  - {line}" for line in brief.risk)
    else:
        out.append("  none")
    return _defuse_backtick_runs("\n".join(out).rstrip() + "\n")


def _render_symbols(out: list[str], a: FileAnalysis, brief: Brief) -> None:
    d = a.deltas()
    if d["added"]:
        out.append("  symbols added:")
        out.extend(f"    + {s.signature()}" for s in d["added"])
    if d["removed"]:
        out.append("  symbols removed:")
        out.extend(f"    - {s.signature()}" for s in d["removed"])
    for sc in (x for x in brief.signature_changes if x.path == a.path):
        out.append(f"  signature changed: {sc.qualname}")
        out.append(f"      old: {sc.old}")
        out.append(f"      new: {sc.new}")
        out.append(f"      {_detail_words(sc.detail)}")
    if a.imports_added or a.imports_removed:
        added = [f"+{n}" for n in sorted(a.imports_added)]
        removed = [f"-{n}" for n in sorted(a.imports_removed)]
        out.append("  imports: " + ", ".join(added + removed))
    if a.docstring_touched:
        out.append("  module docstring touched")
    if a.exports_touched:
        out.append("  __all__ touched")


def _render_placements(out: list[str], a: FileAnalysis) -> None:
    if not a.placements:
        return
    # "top-level" is a claim about where a hunk sits, and only a parsed symbol
    # map can support it. With the delta withheld the map is empty because
    # nothing was established, so an unplaced hunk has to say so out loud.
    unplaced = "top-level" if a.parsed and not a.untrusted else "not attributed"
    parts = []
    for p in a.placements:
        label = ", ".join(p.inside) if p.inside else unplaced
        parts.append(f"hunk@{p.new_start}-{p.new_end} -> {label}")
    out.append("  hunks: " + "; ".join(parts))


def _detail_words(sd: ast_stage.SignatureDiff) -> str:
    bits: list[str] = []
    if sd.params_added:
        bits.append("params +" + ",".join(sd.params_added))
    if sd.params_removed:
        bits.append("params -" + ",".join(sd.params_removed))
    if sd.annotations_changed:
        bits.append("annotations " + ",".join(sd.annotations_changed))
    if sd.defaults_changed:
        bits.append("defaults " + ",".join(sd.defaults_changed))
    if sd.returns_changed:
        bits.append("return annotation")
    if sd.decorators_added:
        bits.append("decorators +" + ",".join(sd.decorators_added))
    if sd.decorators_removed:
        bits.append("decorators -" + ",".join(sd.decorators_removed))
    if sd.methods_added:
        bits.append("methods +" + ",".join(sd.methods_added))
    if sd.methods_removed:
        bits.append("methods -" + ",".join(sd.methods_removed))
    return "; ".join(bits)


def _fmt_moves(brief: Brief) -> str:
    return ", ".join(f"{m.qualname}: {m.frm} -> {m.to}" for m in brief.moves)


def _fmt_renames(brief: Brief) -> str:
    return ", ".join(f"{r.frm}->{r.to} in {r.path}" for r in brief.renames)


def render_json(brief: Brief, summary: str | None = None) -> str:
    """Machine view. When a model summary exists it rides along in the same
    document, so `--format json` never emits two concatenated payloads."""
    data = _to_dict(brief)
    if summary is not None:
        data["summary"] = summary
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _to_dict(brief: Brief) -> dict:
    return {
        "files_changed": brief.files_changed,
        "files": [_file_dict(a, brief) for a in brief.files],
        "cross_file": {
            "public_added": brief.public_added,
            "public_removed": brief.public_removed,
            "moves": [{"name": m.qualname, "from": m.frm, "to": m.to} for m in brief.moves],
            "renames": [{"from": r.frm, "to": r.to, "path": r.path} for r in brief.renames],
        },
        "risk": brief.risk,
    }


def _file_dict(a: FileAnalysis, brief: Brief) -> dict:
    d = a.deltas()
    return {
        "path": a.path,
        "change_type": a.change_type,
        "python": a.python,
        "parsed": a.parsed,
        "untrusted": a.untrusted,
        "note": a.note,
        "lines_added": a.lines_added,
        "lines_removed": a.lines_removed,
        "imports": {"added": sorted(a.imports_added), "removed": sorted(a.imports_removed)},
        "docstring_touched": a.docstring_touched,
        "exports_touched": a.exports_touched,
        "symbols": {
            "added": [_sym_dict(s) for s in d["added"]],
            "removed": [_sym_dict(s) for s in d["removed"]],
        },
        "signature_changes": [
            {
                "name": sc.qualname,
                "old": sc.old,
                "new": sc.new,
                "call_sites": sc.call_sites,
                "detail": {
                    "params_added": list(sc.detail.params_added),
                    "params_removed": list(sc.detail.params_removed),
                    "annotations_changed": list(sc.detail.annotations_changed),
                    "defaults_changed": list(sc.detail.defaults_changed),
                    "returns_changed": sc.detail.returns_changed,
                    "decorators_added": list(sc.detail.decorators_added),
                    "decorators_removed": list(sc.detail.decorators_removed),
                    "methods_added": list(sc.detail.methods_added),
                    "methods_removed": list(sc.detail.methods_removed),
                },
            }
            for sc in brief.signature_changes
            if sc.path == a.path
        ],
        "hunks": [
            {"new_start": p.new_start, "new_end": p.new_end, "inside": list(p.inside)}
            for p in a.placements
        ],
    }


def _sym_dict(s: Symbol) -> dict:
    return {
        "name": s.qualname,
        "kind": s.kind,
        "line": s.lineno,
        "end_line": s.end_lineno,
        "signature": s.signature(),
        "public": s.is_public,
    }
