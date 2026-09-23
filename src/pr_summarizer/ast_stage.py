"""Structural delta of a change, computed from the diff with stdlib ``ast``.

Why this stage exists and why it reads only the diff is in
docs/adr/0001-ast-before-model.md. The one non-obvious rule it lives by: a diff
shows changed regions plus three lines of context, not whole files, so this
module reconstructs the *new side* of each hunk and parses that. A hunk that
begins inside a block has no parseable standalone start; the leading fragment
belongs to a construct whose header the diff never showed, so it is dropped
rather than guessed at. Every symbol reported here was parsed, never inferred
from code the diff does not contain.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from .diff import FileChange

FUNCTION = "function"
ASYNC_FUNCTION = "asyncfunction"
CLASS = "class"


@dataclass(frozen=True)
class Param:
    name: str
    annotation: str | None
    default: str | None
    kind: str  # positional, positional-only, keyword-only, vararg, kwarg

    def render(self) -> str:
        text = self.name
        if self.annotation:
            text += f": {self.annotation}"
        if self.default:
            text += f"={self.default}"
        return text


@dataclass
class Symbol:
    qualname: str  # "parse" or "Resolver.resolve"
    kind: str
    lineno: int
    end_lineno: int
    params: tuple[Param, ...] = ()
    returns: str | None = None
    decorators: tuple[str, ...] = ()
    has_docstring: bool = False
    methods: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.qualname.rsplit(".", 1)[-1]

    @property
    def parent(self) -> str | None:
        return self.qualname.rsplit(".", 1)[0] if "." in self.qualname else None

    @property
    def is_public(self) -> bool:
        return not any(part.startswith("_") for part in self.qualname.split("."))

    @property
    def top_level(self) -> bool:
        return "." not in self.qualname

    def signature(self) -> str:
        if self.kind == CLASS:
            dec = "".join(f"@{d} " for d in self.decorators)
            return f"{dec}class {self.name}"
        kw = "async def" if self.kind == ASYNC_FUNCTION else "def"
        head = f"{self.decorators_prefix()}{kw} {self.name}"
        return f"{head}({self.params_text()}){self.returns_text()}"

    def decorators_prefix(self) -> str:
        return "".join(f"@{d} " for d in self.decorators)

    def returns_text(self) -> str:
        return f" -> {self.returns}" if self.returns else ""

    def params_text(self) -> str:
        # Rebuild the separators Python uses: a bare "*" marks the start of the
        # keyword-only section, and "/" the end of positional-only, so the
        # rendered signature is valid and round-trips against the source.
        parts: list[str] = []
        seen_kw_marker = False
        for p in self.params:
            if p.kind == "keyword-only" and not seen_kw_marker:
                if not any(q.kind == "vararg" for q in self.params):
                    parts.append("*")
                seen_kw_marker = True
            parts.append(p.render())
        return ", ".join(parts)

    def _shape(self) -> tuple:
        return (self.params, self.returns, self.kind)

    def similar_to(self, other: Symbol) -> bool:
        """Same kind and parameter list: the basis for a rename pairing."""
        return self.kind == other.kind and self.params == other.params


@dataclass
class HunkPlacement:
    index: int
    new_start: int
    new_end: int
    inside: tuple[str, ...]  # symbols the hunk overlaps, or () for top-level
    partly_top_level: bool


@dataclass
class FileAnalysis:
    path: str
    change_type: str
    python: bool
    parsed: bool
    untrusted: bool = False
    symbols_new: dict[str, Symbol] = field(default_factory=dict)
    symbols_old: dict[str, Symbol] = field(default_factory=dict)
    imports_added: set[str] = field(default_factory=set)
    imports_removed: set[str] = field(default_factory=set)
    docstring_touched: bool = False
    exports_touched: bool = False
    placements: list[HunkPlacement] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    note: str | None = None

    @property
    def module(self) -> str:
        return re.split(r"[/\\.]", self.path.rsplit("/", 1)[-1])[0]

    def deltas(self) -> dict[str, list[Symbol]]:
        """Added, removed and kept symbols, suppressed when the file is not
        fully parseable so a truncated read is never reported as a removal."""
        if self.untrusted or not self.parsed:
            return {"added": [], "removed": [], "kept": {}}
        added = [s for k, s in self.symbols_new.items() if k not in self.symbols_old]
        removed = [s for k, s in self.symbols_old.items() if k not in self.symbols_new]
        kept = {k: v for k, v in self.symbols_new.items() if k in self.symbols_old}
        return {"added": added, "removed": removed, "kept": kept}


@dataclass
class SignatureDiff:
    params_added: tuple[str, ...] = ()
    params_removed: tuple[str, ...] = ()
    defaults_changed: tuple[str, ...] = ()
    annotations_changed: tuple[str, ...] = ()
    returns_changed: bool = False
    decorators_added: tuple[str, ...] = ()
    decorators_removed: tuple[str, ...] = ()
    methods_added: tuple[str, ...] = ()
    methods_removed: tuple[str, ...] = ()

    @property
    def any(self) -> bool:
        return bool(
            self.params_added
            or self.params_removed
            or self.defaults_changed
            or self.annotations_changed
            or self.returns_changed
            or self.decorators_added
            or self.decorators_removed
            or self.methods_added
            or self.methods_removed
        )


def signature_diff(old: Symbol, new: Symbol) -> SignatureDiff:
    old_params = {p.name: p for p in old.params}
    new_params = {p.name: p for p in new.params}
    added = tuple(sorted(new_params.keys() - old_params.keys()))
    removed = tuple(sorted(old_params.keys() - new_params.keys()))
    shared = sorted(old_params.keys() & new_params.keys())
    defaults = tuple(n for n in shared if old_params[n].default != new_params[n].default)
    annos = tuple(n for n in shared if old_params[n].annotation != new_params[n].annotation)
    old_dec, new_dec = set(old.decorators), set(new.decorators)
    old_m, new_m = set(old.methods), set(new.methods)
    return SignatureDiff(
        params_added=added,
        params_removed=removed,
        defaults_changed=defaults,
        annotations_changed=annos,
        returns_changed=old.returns != new.returns,
        decorators_added=tuple(sorted(new_dec - old_dec)),
        decorators_removed=tuple(sorted(old_dec - new_dec)),
        methods_added=tuple(sorted(new_m - old_m)),
        methods_removed=tuple(sorted(old_m - new_m)),
    )


def detect_renames(removed: list[Symbol], added: list[Symbol]) -> list[tuple[Symbol, Symbol]]:
    """Pair a removed symbol with an added one that kept its shape.

    A rename is a heuristic: same kind and same parameter list is what a rename
    looks like in a diff, but it cannot be distinguished from a coincidental
    extraction. The brief labels rename findings as inferred for that reason.
    """
    pairs: list[tuple[Symbol, Symbol]] = []
    used: set[str] = set()
    for old in removed:
        for new in added:
            if new.qualname in used or not new.top_level or not old.top_level:
                continue
            if old.kind == new.kind and old.params == new.params and old.name != new.name:
                pairs.append((old, new))
                used.add(new.qualname)
                break
    return pairs


def count_call_sites(change: FileChange, name: str) -> int:
    """References to ``name(`` on the new side of a file's changed regions.

    A definition line is skipped: ``def append(`` is the symbol being counted,
    not a use of it. ``x.append(`` is excluded by the lookbehind.
    """
    pattern = re.compile(rf"(?<![\w.]){re.escape(name)}\s*\(")
    hits = 0
    for _, text in change.new_lines():
        stripped = text.lstrip()
        if stripped.startswith(("def ", "async def ", "class ")):
            continue
        hits += len(pattern.findall(text.split("#", 1)[0]))
    return hits


# ---------------------------------------------------------------- public API


def analyze(change: FileChange) -> FileAnalysis:
    analysis = FileAnalysis(
        path=change.path,
        change_type=change.change_type,
        python=change.is_python(),
        parsed=False,
        lines_added=change.added(),
        lines_removed=change.removed(),
    )
    if not analysis.python:
        analysis.note = "no structural analysis for this language"
        return analysis
    if change.binary:
        analysis.note = "binary file"
        return analysis

    new_syms: dict[str, Symbol] = {}
    old_syms: dict[str, Symbol] = {}
    new_imports: set[str] = set()
    old_imports: set[str] = set()
    new_doc: list[str | None] = []
    old_doc: list[str | None] = []
    new_exports: list[bool] = []
    old_exports: list[bool] = []
    any_parsed = False

    for hunk in change.hunks:
        # Parse the new and old side of the same hunk as a matched pair. A side
        # that changes a top-level construct but will not parse makes the whole
        # file untrusted: from a failed parse you cannot conclude a symbol was
        # removed, only that the diff fragment is not readable on its own.
        side_results: dict[str, ast.Module] = {}
        for side, region, changed in (
            ("new", hunk.new_region(), hunk.added_count()),
            ("old", hunk.old_region(), hunk.removed_count()),
        ):
            mod, ok = _parse_region(region)
            if ok and mod is not None:
                side_results[side] = mod
            elif changed and region:
                analysis.untrusted = True

        for side, mod in side_results.items():
            any_parsed = True
            syms = new_syms if side == "new" else old_syms
            for node in mod.body:
                sym = _symbol_from_node(node)
                if sym:
                    syms[sym.qualname] = sym
            target_imports = new_imports if side == "new" else old_imports
            target_imports.update(_module_imports(mod))
            (new_doc if side == "new" else old_doc).append(_module_docstring(mod))
            (new_exports if side == "new" else old_exports).append(_has_all(mod))

    analysis.parsed = any_parsed
    analysis.symbols_new = new_syms
    analysis.symbols_old = old_syms
    analysis.imports_added = new_imports - old_imports
    analysis.imports_removed = old_imports - new_imports
    analysis.docstring_touched = _first_differs(new_doc, old_doc)
    new_has_all = any(new_exports)
    old_has_all = any(old_exports)
    analysis.exports_touched = new_has_all != old_has_all
    if analysis.untrusted:
        analysis.note = "changed region does not parse; structural delta withheld"
    elif not any_parsed:
        analysis.note = "no top-level construct shown; no structural analysis"
    analysis.placements = _place_hunks(change, new_syms)
    return analysis


# -------------------------------------------------------------- region parse


def _dedent_block(lines: list[tuple[int, str]]) -> tuple[list[tuple[int, str]], int] | None:
    """Trim leading lines until the block starts at column zero.

    A hunk can open inside a class body; those indented lines belong to a
    construct whose ``class`` header is not in the diff, so parsing them would
    invent a structure that is not shown. Return the parseable tail and the
    line number it starts on, or None when nothing is left.
    """
    for i, (_, text) in enumerate(lines):
        if text.strip() and not text[:1].isspace():
            return lines[i:], lines[i][0]
    return None


def _parse_region(region: list[tuple[int, str]]) -> tuple[ast.Module | None, bool]:
    """Parse one reconstructed region. Returns (module, parsed)."""
    trimmed = _dedent_block(region)
    if trimmed is None:
        return None, False
    lines, start = trimmed
    # Strip carriage returns: a CRLF file's new side carries them as content,
    # and they are a line-ending artifact, not part of any construct.
    source = "\n".join(text.rstrip("\r") for _, text in lines)
    try:
        mod = ast.parse(source)
    except SyntaxError:
        return None, False
    return _rebase(mod, start), True


def _rebase(mod: ast.Module, start: int) -> ast.Module:
    """Shift a parsed fragment's line numbers onto absolute file numbering."""
    if start <= 1:
        return mod
    for node in ast.walk(mod):
        lineno = getattr(node, "lineno", None)
        if lineno is not None:
            node.lineno += start - 1  # type: ignore[attr-defined]
        end = getattr(node, "end_lineno", None)
        if end is not None:
            node.end_lineno += start - 1  # type: ignore[attr-defined]
    return mod


def _symbol_from_node(node: ast.stmt) -> Symbol | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _symbol_from_func(node)
    if isinstance(node, ast.ClassDef):
        return _symbol_from_class(node)
    return None


def _symbol_from_func(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Symbol:
    kind = ASYNC_FUNCTION if isinstance(node, ast.AsyncFunctionDef) else FUNCTION
    return Symbol(
        qualname=node.name,
        kind=kind,
        lineno=node.lineno,
        end_lineno=node.end_lineno or node.lineno,
        params=_params(node.args),
        returns=_ann(node.returns),
        decorators=tuple(_deco(d) for d in node.decorator_list),
        has_docstring=ast.get_docstring(node) is not None,
    )


def _symbol_from_class(node: ast.ClassDef) -> Symbol:
    methods = tuple(
        f"{node.name}.{c.name}"
        for c in node.body
        if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return Symbol(
        qualname=node.name,
        kind=CLASS,
        lineno=node.lineno,
        end_lineno=node.end_lineno or node.lineno,
        decorators=tuple(_deco(d) for d in node.decorator_list),
        has_docstring=ast.get_docstring(node) is not None,
        methods=methods,
    )


def _params(args: ast.arguments) -> tuple[Param, ...]:
    out: list[Param] = []
    pos = [*args.posonlyargs, *args.args]
    pos_kind = ["positional-only"] * len(args.posonlyargs) + ["positional"] * len(args.args)
    # defaults align to the tail of the positional list.
    n_nodefault = len(pos) - len(args.defaults)
    for i, (a, kind) in enumerate(zip(pos, pos_kind, strict=True)):
        default = None
        di = i - n_nodefault
        if di >= 0:
            default = _src(args.defaults[di])
        out.append(Param(a.arg, _ann(a.annotation), default, kind))
    if args.vararg:
        out.append(Param(f"*{args.vararg.arg}", _ann(args.vararg.annotation), None, "vararg"))
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        out.append(Param(a.arg, _ann(a.annotation), _src(d) if d else None, "keyword-only"))
    if args.kwarg:
        out.append(Param(f"**{args.kwarg.arg}", _ann(args.kwarg.annotation), None, "kwarg"))
    return tuple(out)


def _deco(node: ast.expr) -> str:
    return _src(node)


def _ann(node: ast.expr | None) -> str | None:
    return _src(node) if node is not None else None


def _src(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse is total on parsed trees
        return "<expr>"


def _module_imports(mod: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(mod):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            src = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    names.add(f"{src}.*")
                else:
                    names.add(alias.asname or f"{src}.{alias.name}")
    return names


def _module_docstring(mod: ast.Module) -> str | None:
    return ast.get_docstring(mod)


def _has_all(mod: ast.Module) -> bool:
    return any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets)
        for n in mod.body
    )


def _first_differs(new: list[str | None], old: list[str | None]) -> bool:
    """True when the visible docstrings differ, including a present/absent flip."""
    new_top = next((d for d in new if d is not None), None)
    old_top = next((d for d in old if d is not None), None)
    if new_top is None and old_top is None:
        return False
    return new_top != old_top


def _place_hunks(change: FileChange, syms: dict[str, Symbol]) -> list[HunkPlacement]:
    placements: list[HunkPlacement] = []
    for i, h in enumerate(change.hunks):
        region = h.new_region()
        if not region:
            continue
        lo, hi = region[0][0], region[-1][0]
        inside: list[str] = []
        covered: set[int] = set()
        for s in syms.values():
            if s.lineno <= hi and s.end_lineno >= lo:
                inside.append(s.qualname)
                covered.update(range(max(lo, s.lineno), min(hi, s.end_lineno) + 1))
        partly = any(ln not in covered for ln, _ in region)
        placements.append(
            HunkPlacement(
                index=i,
                new_start=lo,
                new_end=hi,
                inside=tuple(sorted(inside)),
                partly_top_level=partly,
            )
        )
    return placements
