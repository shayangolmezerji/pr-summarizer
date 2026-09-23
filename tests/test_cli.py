"""CLI tests: the real main() against fixture diffs, with model access either
stubbed at the summarize boundary or, for the failure path, replaced at the
transport so the error text is the one the library actually builds."""

from __future__ import annotations

import io
import json

import pytest

from pr_summarizer import cli, model

FAKE_KEY = "sk-fake-not-a-real-key-0123456789"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (model.BASE_URL_ENV, model.MODEL_ENV, model.KEY_ENV):
        monkeypatch.delenv(var, raising=False)


def _fixture(fixtures_dir, name):
    return str(fixtures_dir / f"{name}.diff")


def test_no_config_prints_brief_and_exits_zero(fixtures_dir, capsys):
    code = cli.main([_fixture(fixtures_dir, "shape")])
    assert code == cli.EXIT_OK
    out = capsys.readouterr()
    assert "structural brief:" in out.out
    assert "model skipped" in out.err
    assert "PRSUMMARIZER_BASE_URL" in out.err


def test_text_format_contains_the_risk_read(fixtures_dir, capsys):
    cli.main([_fixture(fixtures_dir, "shape")])
    out = capsys.readouterr().out
    assert "signature of store.py:append changed; 3 call sites" in out


def test_json_format_is_valid_and_carries_files(fixtures_dir, capsys):
    code = cli.main(["--format", "json", _fixture(fixtures_dir, "shape")])
    assert code == cli.EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["files_changed"] == 3


def test_no_model_suppresses_the_attempt(fixtures_dir, capsys, monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("model must not be consulted with --no-model")

    monkeypatch.setattr(model, "summarize", boom)
    code = cli.main(["--no-model", _fixture(fixtures_dir, "shape")])
    assert code == cli.EXIT_OK
    assert called["n"] == 0


def test_model_summary_appended_in_text(fixtures_dir, capsys, monkeypatch):
    monkeypatch.setattr(model, "summarize", lambda *a, **k: "The change widens append().")
    code = cli.main([_fixture(fixtures_dir, "shape")])
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "model summary" in out
    assert "The change widens append()." in out


def test_model_summary_embedded_in_json(fixtures_dir, capsys, monkeypatch):
    monkeypatch.setattr(model, "summarize", lambda *a, **k: "summary text")
    cli.main(["--format", "json", _fixture(fixtures_dir, "shape")])
    data = json.loads(capsys.readouterr().out)
    assert data["summary"] == "summary text"


def test_model_error_still_prints_brief_but_fails_exit(fixtures_dir, capsys, monkeypatch):
    # A real 404 out of the transport, not a hand-built exception: the message
    # naming the suspect variable is produced by model.summarize.
    monkeypatch.setenv(model.BASE_URL_ENV, "https://api.example.invalid/v1")
    monkeypatch.setenv(model.MODEL_ENV, "some-model")
    monkeypatch.setenv(model.KEY_ENV, FAKE_KEY)
    monkeypatch.setattr(model, "_urllib_transport", lambda url, headers, body: (404, b"{}"))

    code = cli.main([_fixture(fixtures_dir, "shape")])
    assert code == cli.EXIT_MODEL
    captured = capsys.readouterr()
    assert "structural brief:" in captured.out
    assert "risk" in captured.out
    assert "PRSUMMARIZER_BASE_URL" in captured.err
    assert FAKE_KEY not in captured.out
    assert FAKE_KEY not in captured.err


def test_stdin_is_read_when_no_path(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", _Stdin(io.BytesIO(_shape_bytes())))
    cli.main([])
    assert "structural brief:" in capsys.readouterr().out


class _Stdin:
    def __init__(self, buf):
        self.buffer = buf

    def isatty(self):
        return False


def _shape_bytes():
    from pathlib import Path

    p = Path(__file__).parent / "fixtures" / "shape.diff"
    return p.read_bytes()


def test_git_source_invokes_git_diff(fixtures_dir, monkeypatch, capsys):
    captured = {}
    diff_bytes = _shape_bytes()

    class Proc:
        stdout = diff_bytes
        stderr = b""
        returncode = 0

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code = cli.main(["--git", "HEAD~1", "HEAD"])
    assert code == cli.EXIT_OK
    assert captured["cmd"] == ["git", "diff", "HEAD~1", "HEAD"]
    assert "structural brief:" in capsys.readouterr().out


def test_git_failure_is_a_usage_error(monkeypatch, capsys):
    import subprocess

    def raise_called(*a, **k):
        raise subprocess.CalledProcessError(128, ["git"], stderr=b"fatal: not a git repo")

    monkeypatch.setattr(cli.subprocess, "run", raise_called)
    code = cli.main(["--git", "HEAD"])
    assert code == cli.EXIT_USAGE
    assert "not a git repo" in capsys.readouterr().err


def test_missing_file_is_a_usage_error(capsys):
    code = cli.main(["/no/such/file.diff"])
    assert code == cli.EXIT_USAGE
    assert "cannot read" in capsys.readouterr().err


def test_max_context_is_forwarded(fixtures_dir, monkeypatch):
    seen = {}

    def spy(text, **kw):
        seen["max_bytes"] = kw.get("max_bytes")
        return "ok"

    monkeypatch.setattr(model, "summarize", spy)
    cli.main(["--max-context", "256", _fixture(fixtures_dir, "shape")])
    assert seen["max_bytes"] == 256


def test_empty_diff_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", _Stdin(io.BytesIO(b"")))
    code = cli.main([])
    assert code == cli.EXIT_OK
    assert "0 file(s) changed" in capsys.readouterr().out
