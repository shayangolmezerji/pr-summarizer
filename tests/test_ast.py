"""Tests for the AST stage, driven by the same real git fixtures.

These are the core tests of the tool: they assert what the structural delta
says, not how it was computed, and every expectation traces to a construct that
is literally present in a fixture diff.
"""

from __future__ import annotations

from pr_summarizer import ast_stage, diff


def _files(fixtures_dir, name):
    return {
        c.path: ast_stage.analyze(c)
        for c in diff.parse((fixtures_dir / f"{name}.diff").read_bytes().decode("utf-8"))
    }


def test_non_python_is_marked_not_parsed(fixtures_dir):
    a = _files(fixtures_dir, "mixed_lang")["README.md"]
    assert a.python is False
    assert a.note == "no structural analysis for this language"
    # Line stats still land, so the file is not silently dropped.
    assert a.lines_added >= 1


def test_python_and_nonpython_split_in_one_diff(fixtures_dir):
    a = _files(fixtures_dir, "mixed_lang")
    assert a["app.py"].python
    assert not a["config.yaml"].python


def test_signature_change_widens_params_and_return(fixtures_dir):
    store = _files(fixtures_dir, "shape")["store.py"]
    old = store.symbols_old["append"]
    new = store.symbols_new["append"]
    d = ast_stage.signature_diff(old, new)
    assert d.any
    assert "sync" in d.params_added
    assert d.returns_changed
    assert d.annotations_changed
    assert "path" in d.annotations_changed


def test_moved_symbol_is_removed_here_and_added_there(fixtures_dir):
    a = _files(fixtures_dir, "shape")
    assert "combine" in [s.qualname for s in a["store.py"].deltas()["removed"]]
    assert "combine" in [s.qualname for s in a["ops.py"].deltas()["added"]]


def test_import_added(fixtures_dir):
    store = _files(fixtures_dir, "shape")["store.py"]
    assert "os" in store.imports_added
    assert "os" not in store.imports_removed


def test_module_docstring_touched(fixtures_dir):
    store = _files(fixtures_dir, "shape")["store.py"]
    assert store.docstring_touched


def test_hunk_inside_a_symbol_is_attributed(fixtures_dir):
    store = _files(fixtures_dir, "shape")["store.py"]
    # The hunk that changes append() must be attributed to append, not top-level.
    append_hunks = [p for p in store.placements if "append" in p.inside]
    assert append_hunks
    assert all(p.inside for p in append_hunks)


def test_added_file_symbols_are_all_new(fixtures_dir):
    ops = _files(fixtures_dir, "shape")["ops.py"]
    assert [s.qualname for s in ops.deltas()["added"]] == ["combine"]
    assert ops.deltas()["removed"] == []
    # combine is a function with two positional params.
    combine = ops.symbols_new["combine"]
    assert combine.kind == ast_stage.FUNCTION
    assert [p.name for p in combine.params] == ["a", "b"]


def test_deleted_file_symbols_are_all_gone(fixtures_dir):
    gone = _files(fixtures_dir, "lifecycle")["gone.py"]
    assert [s.qualname for s in gone.deltas()["removed"]] == ["gone"]
    assert gone.symbols_new == {}


def test_mode_only_change_has_no_analysis(fixtures_dir):
    tool = _files(fixtures_dir, "lifecycle")["tool.sh"]
    assert tool.python is False


def test_mode_only_change_carries_no_symbols(fixtures_dir):
    tool = _files(fixtures_dir, "lifecycle")["tool.sh"]
    assert tool.symbols_new == {}
    assert tool.symbols_old == {}


def test_rename_with_edit_still_maps_the_moved_helper(fixtures_dir):
    a = _files(fixtures_dir, "lifecycle")
    renamed = a["renamed.py"]
    assert renamed.change_type == diff.RENAMED
    assert "helper" in renamed.symbols_new


def test_symbol_rename_is_detected_within_a_file(fixtures_dir):
    mod = _files(fixtures_dir, "symbols")["symbols_mod.py"]
    delta = mod.deltas()
    pairs = ast_stage.detect_renames(delta["removed"], delta["added"])
    renamed = {(o.name, n.name) for o, n in pairs}
    assert ("legacy", "current") in renamed


def test_decorator_added_and_dropped(fixtures_dir):
    mod = _files(fixtures_dir, "symbols")["symbols_mod.py"]
    # compute kept its name but lost @functools.lru_cache.
    sd = ast_stage.signature_diff(mod.symbols_old["compute"], mod.symbols_new["compute"])
    assert sd.decorators_removed == ("functools.lru_cache",)


def test_method_added_to_class(fixtures_dir):
    mod = _files(fixtures_dir, "symbols")["symbols_mod.py"]
    sd = ast_stage.signature_diff(mod.symbols_old["Bag"], mod.symbols_new["Bag"])
    assert sd.methods_added == ("Bag.second",)
    assert not sd.methods_removed


def test_crlf_file_still_parses(fixtures_dir):
    win = _files(fixtures_dir, "crlf")["win.py"]
    assert win.parsed
    assert "greet" in win.symbols_new
    assert win.symbols_new["greet"].params[0].name == "name"


def test_unparseable_change_withholds_delta(fixtures_dir):
    broken = _files(fixtures_dir, "unparse")["broken.py"]
    # The changed region will not parse, so nothing may be reported as removed:
    # a failed parse is not evidence of a deletion.
    assert broken.untrusted is True
    assert broken.deltas() == {"added": [], "removed": [], "kept": {}}
    assert "does not parse" in broken.note


def test_call_sites_counted_on_new_side(fixtures_dir):
    files = diff.parse((_ := fixtures_dir / "shape.diff").read_bytes().decode("utf-8"))
    callers = next(f for f in files if f.path == "callers.py")
    assert ast_stage.count_call_sites(callers, "append") == 3


def test_keyword_only_param_flagged(fixtures_dir):
    store = _files(fixtures_dir, "shape")["store.py"]
    sync = next(p for p in store.symbols_new["append"].params if p.name == "sync")
    assert sync.kind == "keyword-only"
    assert sync.default == "False"
    assert sync.annotation == "bool"


def test_public_surface_and_module_naming(fixtures_dir):
    files = diff.parse((fixtures_dir / "shape.diff").read_bytes().decode("utf-8"))
    store = next(f for f in files if f.path == "store.py")
    a = ast_stage.analyze(store)
    assert a.symbols_new["append"].is_public  # no leading underscore
    assert a.symbols_new["append"].top_level
    assert a.module == "store"


def test_underscored_symbol_is_not_public():
    s = ast_stage.Symbol(qualname="Resolver._load", kind=ast_stage.FUNCTION, lineno=1, end_lineno=2)
    assert not s.is_public
    assert s.parent == "Resolver"


def test_hunk_outside_every_symbol_is_top_level():
    # A minimal crafted hunk, not a fixture: this checks the placement rule in
    # isolation (a change at module level attributes to no symbol).
    change = diff.parse(
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1 +1,2 @@\n"
        " X = 1\n"
        "+Y = 2\n"
    )[0]
    a = ast_stage.analyze(change)
    assert a.parsed
    assert not a.untrusted
    assert a.deltas()["added"] == []  # module-level assignment is not a symbol
    placement = a.placements[0]
    assert placement.inside == ()
    assert placement.partly_top_level
