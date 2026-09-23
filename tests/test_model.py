"""Tests for model access. Every call uses a fake transport except the one that
checks what a refused port does, and that one reaches loopback only.

The load-bearing assertions are that the outgoing body is the brief plus the
instruction (not the raw diff), and that the API key never appears in any value
this module returns or raises.
"""

from __future__ import annotations

import json
import socket

import pytest

from pr_summarizer import brief as brief_mod
from pr_summarizer import model

FAKE_KEY = "sk-fake-not-a-real-key-0123456789"
ENV = {
    model.BASE_URL_ENV: "https://example.invalid/v1",
    model.MODEL_ENV: "some-model",
    model.KEY_ENV: FAKE_KEY,
}


def _fake_transport(status=200, content="An architectural summary."):
    captured = {}

    def transport(url, headers, body):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        payload = {"choices": [{"message": {"content": content}}]}
        return status, json.dumps(payload).encode()

    return transport, captured


def test_missing_base_url_names_the_variable():
    with pytest.raises(model.NotConfiguredError) as exc:
        model.Config.from_env({model.MODEL_ENV: "m"})
    assert exc.value.missing == model.BASE_URL_ENV


def test_missing_model_names_the_variable():
    with pytest.raises(model.NotConfiguredError) as exc:
        model.Config.from_env({model.BASE_URL_ENV: "https://x.invalid/v1"})
    assert exc.value.missing == model.MODEL_ENV


def test_api_key_is_optional_for_local_endpoints():
    cfg = model.Config.from_env(
        {model.BASE_URL_ENV: "http://127.0.0.1:8000/v1", model.MODEL_ENV: "m"}
    )
    assert cfg.api_key is None


def test_url_is_chat_completions_under_the_base():
    transport, cap = _fake_transport()
    model.summarize("BRIEF", environ=ENV, transport=transport)
    assert cap["url"] == "https://example.invalid/v1/chat/completions"


def test_body_carries_the_brief_and_the_instruction():
    transport, cap = _fake_transport()
    model.summarize("THE STRUCTURAL BRIEF", environ=ENV, transport=transport)
    payload = json.loads(cap["body"])
    assert payload["model"] == "some-model"
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["system", "user"]
    assert payload["messages"][1]["content"] == "THE STRUCTURAL BRIEF"
    assert "architectural summary" in payload["messages"][0]["content"]


def test_key_travels_only_in_the_authorization_header():
    transport, cap = _fake_transport()
    result = model.summarize("BRIEF", environ=ENV, transport=transport)
    assert cap["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in result
    assert FAKE_KEY.encode() not in cap["body"]


def test_max_bytes_truncates_the_brief_before_sending():
    transport, cap = _fake_transport()
    big = "x" * 5000
    model.summarize(big, environ=ENV, transport=transport, max_bytes=100)
    sent = json.loads(cap["body"])["messages"][1]["content"]
    assert len(sent.encode()) < 500
    assert "truncated" in sent


@pytest.mark.parametrize(
    "status,suspect",
    [(401, model.KEY_ENV), (403, model.KEY_ENV), (404, model.BASE_URL_ENV), (429, model.MODEL_ENV)],
)
def test_error_names_probable_env_without_the_key(status, suspect):
    def transport(url, headers, body):
        return status, b"{}"

    with pytest.raises(model.ModelError) as exc:
        model.summarize("BRIEF", environ=ENV, transport=transport)
    assert exc.value.suspect_env == suspect
    assert suspect in str(exc.value)
    assert FAKE_KEY not in str(exc.value)


def test_unreachable_endpoint_is_a_model_error_naming_the_base_url():
    # A bound socket nobody ever listens on, so connect is refused at once, and
    # held open so no other process can take the port mid-test. The transport is
    # the real one: this is the case a fake transport cannot represent.
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    port = held.getsockname()[1]
    try:
        with pytest.raises(model.ModelError) as exc:
            model.summarize(
                "BRIEF",
                environ={**ENV, model.BASE_URL_ENV: f"http://127.0.0.1:{port}/v1"},
            )
    finally:
        held.close()
    assert exc.value.suspect_env == model.BASE_URL_ENV
    assert model.BASE_URL_ENV in str(exc.value)
    assert FAKE_KEY not in str(exc.value)


def test_unreadable_body_is_an_error_not_a_crash():
    def transport(url, headers, body):
        return 200, b"not json"

    with pytest.raises(model.ModelError):
        model.summarize("BRIEF", environ=ENV, transport=transport)
    with pytest.raises(model.ModelError):
        model.summarize("BRIEF", environ=ENV, transport=lambda *a: (200, b'{"choices": []}'))


def test_summarize_sends_the_rendered_brief_end_to_end(fixtures_dir):
    text = (fixtures_dir / "shape.diff").read_bytes().decode("utf-8")
    rendered = brief_mod.render_text(brief_mod.build(text))
    transport, cap = _fake_transport(content="append widened; combine moved")
    out = model.summarize(rendered, environ=ENV, transport=transport)
    sent = json.loads(cap["body"])["messages"][1]["content"]
    assert sent == rendered  # the brief, not the diff
    assert "diff --git" not in sent
    assert out == "append widened; combine moved"
