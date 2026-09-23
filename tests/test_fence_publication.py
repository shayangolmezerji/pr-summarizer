"""The publication boundary: who defuses what, and who is allowed to write a fence.

The bytes a fence wraps are the CLI's whole stdout, which is the brief plus, when
a model answered, prose this tool never parsed and `render_text` never saw, so the
guard sits at the block and not upstream of it. The block tests below are
behavioural; the checks on `action.yml` and the workflow are structural, because
nothing here runs a workflow and a shell body a reader cannot execute is a claim,
not a result.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pr_summarizer import brief, model

ROOT = Path(__file__).resolve().parents[1]

# What closes an open backtick fence: up to three spaces of indent, three or more
# backticks, nothing but spaces after them. Inside a fence CommonMark parses
# nothing else, so this is the only shape that matters.
_FENCE_LINE = re.compile(r" {0,3}`{3,} *")
# A line ending as CommonMark sees it, which includes a lone carriage return.
_CM_LINES = re.compile(r"\r\n|\r|\n")

# The two shell bodies that put this text inside a fence.
_FENCE_WRITERS = ("action.yml", ".github/workflows/pr-summary.yml")


def _crlf_patch(name: str) -> str:
    """The shape behind README's published block: a CRLF-header patch whose one
    file is named `name`. `git diff` writes LF headers, so this arrives as a
    fetched or hand-built patch; the parser keeps the CR as part of the path.
    """
    return (
        "\r\n".join(
            [
                f"diff --git a/{name} b/{name}",
                "index 0000000..1111111 100644",
                f"--- a/{name}",
                f"+++ b/{name}",
                "@@ -0,0 +1 @@",
                "+x = 1",
            ]
        )
        + "\r\n"
    )


def _closers(text: str) -> list[str]:
    return [ln for ln in _CM_LINES.split(text) if _FENCE_LINE.fullmatch(ln)]


def test_model_prose_reaching_a_fence_is_not_the_briefs_defusable_text():
    # The premise of the fix: render_text only ever sees the brief, so a
    # response carrying a line of three backticks arrives at the fence live.
    stdout = brief.render_text(brief.build(_crlf_patch("```"))) + "\nmodel summary\n"
    stdout += "-" * 40 + "\nHere is the shape it asked about.\n```\nnot code at all\n```\n"
    assert _closers(stdout) == ["```", "```"]


def test_the_block_the_helper_writes_cannot_be_closed_from_inside():
    stdout = brief.render_text(brief.build(_crlf_patch("```"))) + "\nmodel summary\n"
    stdout += "-" * 40 + "\nHere is the shape it asked about.\n```\nnot code at all\n```\n"
    block = brief.fenced(stdout)
    interior = _CM_LINES.split(block.rstrip("\n"))[1:-1]
    assert [ln for ln in interior if _FENCE_LINE.fullmatch(ln)] == []
    # Defused, not dropped: the words are all still there, and so is every
    # backtick the input carried.
    assert "not code at all" in block
    assert sum(ln.count("`") for ln in interior) == stdout.count("`")


def test_fencing_an_already_defused_brief_adds_nothing_but_the_block():
    text = brief.render_text(brief.build(_crlf_patch("```")))
    assert brief.fenced(text) == "```text\n" + text.rstrip("\n") + "\n```\n"


# A string literal typed by the diff's author: the other way a run of backticks
# gets into a brief, with no carriage return involved. `ast.unparse` renders this
# literal with single quotes, so the defused form is spelled out below rather than
# guessed at.
_TICK_DIFF = (
    "diff --git a/ticks.py b/ticks.py\n"
    "new file mode 100644\n"
    "index 0000000..1111111\n"
    "--- /dev/null\n"
    "+++ b/ticks.py\n"
    "@@ -0,0 +1,4 @@\n"
    "+from typing import Literal\n"
    "+\n"
    "+\n"
    '+def f(x: Literal["```"]) -> None: ...\n'
)


def test_the_provider_is_handed_the_defused_text_view():
    # cli.py sends render_text's output to the model, so the escaping that
    # protects a published block is also what an endpoint reads: the run arrives
    # with a backslash in front of it, one character deeper than the file said.
    rendered = brief.render_text(brief.build(_TICK_DIFF))
    cfg = model.Config(base_url="https://example.invalid/v1", model="m", api_key=None)
    _, _, body = model.build_request(cfg, rendered)
    content = json.loads(body)["messages"][1]["content"]
    assert r"Literal['\```']" in content
    assert "Literal['```']" not in content


def test_whoever_writes_a_fence_calls_the_helper():
    for rel in _FENCE_WRITERS:
        text = (ROOT / rel).read_text()
        assert "from pr_summarizer.brief import fenced" in text, rel
        # No hand-written fence left: the opener and the closer come from one place.
        assert "```text" not in text, rel


def _run_bodies(text: str) -> list[list[str]]:
    """The lines of each `run: |` block, in order of appearance."""
    bodies: list[list[str]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.rstrip().endswith("run: |"):
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for following in lines[i + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following.strip())
        bodies.append(body)
    return bodies


def test_every_shell_body_in_the_publishing_path_sets_the_ballot_options():
    # The step that publishes is the step that must not half-run: an unset
    # variable or a failed pipe stops it, in both files, the same way. The
    # comment step is the sibling that had not been told. The count is the
    # guard against the scanner quietly finding nothing to check.
    checked = 0
    for rel in _FENCE_WRITERS:
        for body in _run_bodies((ROOT / rel).read_text()):
            if not body:
                continue
            checked += 1
            assert body[0] == "set -euo pipefail", f"{rel}: {body[0]}"
    assert checked == 2


_USES = re.compile(r"^ *(?:- )?uses: (\S+)(.*)$")
_TAG_REF = re.compile(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}")
_RELEASE_NOTE = re.compile(r" # v[0-9][\w.+-]*")


def test_every_action_this_repo_points_at_is_pinned_to_a_commit():
    """`uses: ./` is this checkout; everything else is somebody else's tag.

    The workflow that calls this action fires on pull_request with
    pull-requests: write, so a moving upstream tag is a path onto a runner
    holding that token. Checked across all three files, including ci.yml,
    which is not edited here: the claim being tested is the repo's, not one
    file's.
    """
    checked = 0
    for rel in ("action.yml", ".github/workflows/ci.yml", ".github/workflows/pr-summary.yml"):
        for line in (ROOT / rel).read_text().splitlines():
            m = _USES.match(line)
            if m is None:
                continue
            checked += 1
            ref, rest = m.groups()
            if ref == "./":
                continue
            assert _TAG_REF.fullmatch(ref), f"{rel}: {line}"
            assert _RELEASE_NOTE.fullmatch(rest), f"{rel}: {line}"
    assert checked == 5
