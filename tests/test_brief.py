"""Tests for the brief and its two renderings.

Determinism is a contract here, not a nicety: the same diff must render to the
same bytes, and the text and json views must agree because they read one object.
"""

from __future__ import annotations

import json

import pytest

from pr_summarizer import brief


def _read(fixtures_dir, name):
    return (fixtures_dir / f"{name}.diff").read_bytes().decode("utf-8")


def _brief(fixtures_dir, name):
    return brief.build(_read(fixtures_dir, name))


def test_risk_line_names_symbol_and_call_sites(fixtures_dir):
    b = _brief(fixtures_dir, "shape")
    line = next(x for x in b.risk if "append" in x)
    assert "signature of store.py:append changed" in line
    assert "3 call sites in this diff" in line


def test_move_is_reported_once_and_not_as_public_removal(fixtures_dir):
    b = _brief(fixtures_dir, "shape")
    assert [(m.qualname, m.frm, m.to) for m in b.moves] == [("combine", "store.py", "ops.py")]
    # combine left store.py and arrived in ops.py; that is not a public removal.
    assert "store.combine" not in b.public_removed
    assert "ops.combine" not in b.public_added


def test_keyword_only_marker_in_rendered_signature(fixtures_dir):
    b = _brief(fixtures_dir, "shape")
    sc = next(x for x in b.signature_changes if x.qualname == "append")
    assert "*, sync: bool=False" in sc.new
    assert "-> bool" in sc.new


def test_signature_changes_include_annotations_and_return(fixtures_dir):
    b = _brief(fixtures_dir, "shape")
    sc = next(x for x in b.signature_changes if x.qualname == "append")
    assert sc.detail.returns_changed
    assert "path" in sc.detail.annotations_changed


def test_public_added_after_a_rename_pairs_not_counts_it(fixtures_dir):
    b = _brief(fixtures_dir, "symbols")
    # legacy->current is a rename; it must not also be counted as a bare public
    # removal (current) or a bare public addition — the rename is the fact.
    renames = [(r.frm, r.to) for r in b.renames if r.path == "symbols_mod.py"]
    assert renames == [("legacy", "current")]
    assert "symbols_mod.current" not in b.public_added
    assert "symbols_mod.legacy" not in b.public_removed


def test_mixed_language_non_python_has_stats_no_analysis(fixtures_dir):
    b = _brief(fixtures_dir, "mixed_lang")
    readme = next(f for f in b.files if f.path == "README.md")
    text = brief.render_text(b)
    assert "no structural analysis for this language" in text
    assert readme.lines_added >= 1


def test_untrusted_file_shows_a_withheld_delta(fixtures_dir):
    text = brief.render_text(_brief(fixtures_dir, "unparse"))
    assert "does not parse" in text
    assert "delta withheld" in text


def test_withheld_delta_does_not_claim_a_hunk_position(fixtures_dir):
    # An empty symbol map from a failed parse is not evidence that a hunk sits
    # outside every symbol, so the render must not print the position label.
    text = brief.render_text(_brief(fixtures_dir, "unparse"))
    assert "not attributed" in text
    assert "top-level" not in text
    # Where the map is real, the label still means what it says.
    assert "top-level" in brief.render_text(_brief(fixtures_dir, "shape"))


def test_empty_diff_renders_zero_files(fixtures_dir):
    b = _brief(fixtures_dir, "empty")
    assert b.files_changed == 0
    assert "0 file(s) changed" in brief.render_text(b)
    assert json.loads(brief.render_json(b))["files_changed"] == 0


def test_json_is_valid_and_deterministic(fixtures_dir):
    b = _brief(fixtures_dir, "shape")
    first = brief.render_json(b)
    again = brief.render_json(_brief(fixtures_dir, "shape"))
    assert first == again
    data = json.loads(first)
    assert data["files_changed"] == 3


def test_text_and_json_describe_the_same_change(fixtures_dir):
    b = _brief(fixtures_dir, "shape")
    text = brief.render_text(b)
    data = json.loads(brief.render_json(b))
    # Whatever the text says changed, the json must carry, and vice versa.
    assert ("signature changed: append" in text) == any(
        sc["name"] == "append"
        for f in data["files"]
        for sc in f["signature_changes"]
    )
    assert bool(data["cross_file"]["moves"]) == ("combine moved" in text)


def test_risk_lines_all_present_in_json(fixtures_dir):
    b = _brief(fixtures_dir, "symbols")
    data = json.loads(brief.render_json(b))
    assert data["risk"] == b.risk


@pytest.mark.parametrize(
    "name", ["shape", "lifecycle", "mixed_lang", "symbols", "crlf", "unparse", "empty"]
)
def test_both_formats_render_for_every_fixture(fixtures_dir, name):
    b = _brief(fixtures_dir, name)
    assert brief.render_text(b)
    json.loads(brief.render_json(b))
