"""Tests for the unified-diff parser, driven by real `git diff` fixtures."""

from __future__ import annotations

import pytest

from pr_summarizer import diff


def _load(fixtures_dir, name):
    # read_bytes().decode() rather than read_text(): read_text applies universal
    # newline translation, which would erase the "\r" the crlf fixture carries.
    return (fixtures_dir / f"{name}.diff").read_bytes().decode("utf-8")


def test_shape_groups_three_files(fixtures_dir):
    files = diff.parse(_load(fixtures_dir, "shape"))
    assert [f.path for f in files] == ["callers.py", "ops.py", "store.py"]


def test_added_file_has_no_old_path_and_full_new_side(fixtures_dir):
    files = {f.path: f for f in diff.parse(_load(fixtures_dir, "shape"))}
    ops = files["ops.py"]
    assert ops.change_type == diff.ADDED
    assert ops.new_path == "ops.py"
    # An added file's diff carries every line, so reconstruction is complete.
    text = "\n".join(t for _, t in ops.new_lines())
    assert text.startswith('"""Helpers')
    assert "def combine(a, b):" in text


def test_hunk_line_numbering_tracks_additions_and_context(fixtures_dir):
    files = {f.path: f for f in diff.parse(_load(fixtures_dir, "shape"))}
    store = files["store.py"]
    # The first store.py hunk starts at old line 1, new line 1; the docstring
    # swap is one removed plus one added, so new numbering resumes contiguously.
    first = store.hunks[0]
    assert (first.old_start, first.new_start) == (1, 1)
    assert first.header == "" or first.header  # header may carry git's context
    region = dict(first.new_region())
    assert region[1] == '"""Persistence for app state, newline-safe."""'
    assert any(t == "import os" for t in region.values())


def test_end_of_file_hunk_has_no_trailing_context(fixtures_dir):
    store = next(f for f in diff.parse(_load(fixtures_dir, "shape")) if f.path == "store.py")
    last = store.hunks[-1]
    # combine() is deleted at the tail: the removed lines are old-only.
    assert any(t.startswith("def combine") for _, t in last.old_region())
    assert all(not t.startswith("def combine") for _, t in last.new_region())


def test_signature_change_lines_are_present_on_both_sides(fixtures_dir):
    store = next(f for f in diff.parse(_load(fixtures_dir, "shape")) if f.path == "store.py")
    old_text = "\n".join(t for _, t in store.old_lines())
    new_text = "\n".join(t for _, t in store.new_lines())
    assert "def append(path, record):" in old_text
    assert "def append(path: str, record: Record, *, sync: bool = False) -> bool:" in new_text


def test_rename_carries_similarity_and_both_paths(fixtures_dir):
    files = {f.new_path: f for f in diff.parse(_load(fixtures_dir, "lifecycle"))}
    moved = files["renamed.py"]
    assert moved.change_type == diff.RENAMED
    assert moved.old_path == "moved.py"
    assert moved.similarity == 87
    assert moved.hunks, "a rename with an edit still has a hunk"


def test_mode_only_change_has_no_hunks(fixtures_dir):
    tool = next(f for f in diff.parse(_load(fixtures_dir, "lifecycle")) if f.path == "tool.sh")
    assert tool.change_type == diff.MODE
    assert tool.old_mode == "100644"
    assert tool.new_mode == "100755"
    assert tool.hunks == []


def test_deleted_file_marked(fixtures_dir):
    files = {f.path: f for f in diff.parse(_load(fixtures_dir, "lifecycle"))}
    gone = files["gone.py"]
    assert gone.change_type == diff.DELETED
    assert gone.new_path == "/dev/null"
    assert gone.is_python()


def test_crlf_new_side_keeps_carriage_returns(fixtures_dir):
    files = diff.parse(_load(fixtures_dir, "crlf"))
    win = files[0]
    added = [t for t in (x for _, x in win.new_lines()) if "return" in t]
    assert added
    assert all(t.endswith("\r") for t in added)


def test_no_newline_marker_is_not_numbered(fixtures_dir):
    win = diff.parse(_load(fixtures_dir, "crlf"))[0]
    hunk = win.hunks[0]
    markers = [ln for ln in hunk.lines if ln.kind == "\\"]
    assert markers
    assert all(ln.new_no is None and ln.old_no is None for ln in markers)
    # Numbering must not be thrown off by the marker line.
    assert max(n for n, _ in hunk.new_region()) == 3


def test_empty_diff_yields_no_files(fixtures_dir):
    assert diff.parse(_load(fixtures_dir, "empty")) == []


def test_mixed_language_flags_python_only(fixtures_dir):
    files = diff.parse(_load(fixtures_dir, "mixed_lang"))
    assert {f.path for f in files} == {"README.md", "app.py", "config.yaml"}
    assert [f.path for f in files if f.is_python()] == ["app.py"]


def test_added_and_removed_line_counts(fixtures_dir):
    app = next(f for f in diff.parse(_load(fixtures_dir, "mixed_lang")) if f.path == "app.py")
    assert app.added() == 2
    assert app.removed() == 2


def test_format_patch_banner_is_ignored():
    banner = (
        "From 1234567890abcdef Mon Sep 17 00:00:00 2001\n"
        "Subject: [PATCH] change a file\n\n"
        "some commit body text\n\n"
        "---\n"
        " src/a.py | 2 +-\n"
        "\n"
        "diff --git a/src/a.py b/src/a.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    files = diff.parse(banner)
    assert [f.path for f in files] == ["src/a.py"]
    assert files[0].change_type == diff.MODIFIED


def test_binary_change_is_flagged():
    text = (
        "diff --git a/logo.png b/logo.png\n"
        "index 1234567..89abcde 100644\n"
        "Binary files a/logo.png and b/logo.png differ\n"
    )
    files = diff.parse(text)
    assert files[0].binary is True
    assert files[0].hunks == []


@pytest.mark.parametrize("name", ["shape", "lifecycle", "crlf", "mixed_lang", "symbols", "unparse"])
def test_every_fixture_parses_without_error(fixtures_dir, name):
    diff.parse(_load(fixtures_dir, name))
