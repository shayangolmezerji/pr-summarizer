"""Optional model access: one OpenAI-compatible request, stdlib only.

The brief, not the raw diff, is what gets sent. The request is assembled in
``build_request`` and handed to a transport callable, so the network is a seam
a test can replace; nothing here opens a socket unless the default transport is
used. Absent configuration is a normal path, not an error: the caller prints
the structural brief and says why it stopped.

The API key is read from the environment and placed only in the Authorization
header of the outgoing request. It is never interpolated into a result, an
error message or a log line, which is the property the tests pin down.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

BASE_URL_ENV = "PRSUMMARIZER_BASE_URL"
MODEL_ENV = "PRSUMMARIZER_MODEL"
KEY_ENV = "PRSUMMARIZER_API_KEY"

INSTRUCTION = (
    "You are reviewing a code change. Below is a structural brief of a "
    "pull-request diff: which functions and classes were added, removed, "
    "renamed or moved, whose signatures changed, and which hunks land inside "
    "which symbol. It was computed from the diff with a parser, not read line "
    "by line. Write an architectural summary of the change: its intent, the "
    "risk in it, and anything a reviewer should check. Do not describe lines; "
    "describe the change."
)

# (url, headers, body_bytes) -> (status, response_bytes). Injectable for tests.
Transport = Callable[[str, dict[str, str], bytes], tuple[int, bytes]]


class NotConfiguredError(Exception):
    """Model access is off; names the variable that is missing."""

    def __init__(self, missing: str):
        super().__init__(f"{missing} is not set")
        self.missing = missing


class ModelError(Exception):
    """A model call failed. Carries which variable is probably wrong."""

    def __init__(self, message: str, suspect_env: str | None = None):
        super().__init__(message)
        self.suspect_env = suspect_env


@dataclass
class Config:
    base_url: str
    model: str
    api_key: str | None

    @classmethod
    def from_env(cls, environ: dict[str, str]) -> Config:
        base = environ.get(BASE_URL_ENV, "").strip()
        model = environ.get(MODEL_ENV, "").strip()
        if not base:
            raise NotConfiguredError(BASE_URL_ENV)
        if not model:
            raise NotConfiguredError(MODEL_ENV)
        return cls(base_url=base, model=model, api_key=environ.get(KEY_ENV) or None)


def build_request(config: Config, brief_text: str) -> tuple[str, dict[str, str], bytes]:
    url = config.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": brief_text},
        ],
        "temperature": 0,
    }
    return url, headers, json.dumps(payload).encode("utf-8")


def _urllib_transport(url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def summarize(
    brief_text: str,
    *,
    environ: dict[str, str] | None = None,
    transport: Transport | None = None,
    max_bytes: int | None = None,
) -> str:
    config = Config.from_env(os.environ if environ is None else environ)
    text = brief_text
    if max_bytes is not None:
        text = _truncate_to_bytes(text, max_bytes)
    url, headers, body = build_request(config, text)
    status, response = (transport or _urllib_transport)(url, headers, body)
    if status in (401, 403):
        raise ModelError(
            f"model rejected the request (HTTP {status}); check {KEY_ENV} "
            f"and {MODEL_ENV}",
            suspect_env=KEY_ENV,
        )
    if status == 404:
        raise ModelError(
            f"model endpoint not found (HTTP 404); check {BASE_URL_ENV} "
            f"and {MODEL_ENV}",
            suspect_env=BASE_URL_ENV,
        )
    if status == 429:
        raise ModelError(
            f"model rate-limited (HTTP 429); retry, or lower the request "
            f"rate for {MODEL_ENV}",
            suspect_env=MODEL_ENV,
        )
    if status >= 400:
        raise ModelError(f"model call failed (HTTP {status})")
    return _extract_content(response)


def _extract_content(response: bytes) -> str:
    try:
        data = json.loads(response.decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ModelError("model returned a body this tool could not read") from exc


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return cut + "\n... [brief truncated to the context budget]"
