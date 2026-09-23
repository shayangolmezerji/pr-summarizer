# pr-summarizer

Structural summaries of a pull-request diff, computed with the standard
library's `ast`.

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

No CI badge: the workflow in `.github/workflows/` has never been run by GitHub,
and a badge pointing at a job that has never executed is a claim, not a result.
[Limitations](#limitations) lists what has and has not been executed here.

## Table of Contents

- [What it does](#what-it-does)
- [The output](#the-output)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Flags](#flags)
- [Exit codes](#exit-codes)
- [Model access](#model-access)
- [GitHub Action](#github-action)
- [Testing](#testing)
- [Limitations](#limitations)
- [License](#license)

## What it does

It reads a unified diff and answers a structural question about it: which
functions and classes appeared, vanished, moved between files, or had a
signature widened, and how many times this same diff calls the thing whose
signature moved.

A diff says `+def append(path,`. That is a line. "The signature of a public
function widened and this diff calls it in three places" is not in the diff
anywhere, and reconstructing it from a few thousand lines of `+`/`-` noise is
where a reviewer loses the change. The brief is the answer, computed by parsing
the code, not by reading it.

The brief is the product. A language model is an optional renderer bolted on
top of it, and the default state of an install is no model configured. The tool
is useful with no network in that state, and that is not a degraded mode.

Zero runtime dependencies. The reasoning and the cost of it are in
[ADR 0001](docs/adr/0001-ast-before-model.md); `docs/spec.md` is the contract
the code is written against.

## The output

Every byte below is from one real run of one real command on
`tests/fixtures/shape.diff`, a `git diff` captured from a scratch repository.

```
$ .venv/bin/pr-summarizer tests/fixtures/shape.diff
model not configured (PRSUMMARIZER_BASE_URL is not set); the structural brief does not need one
structural brief: 3 file(s) changed

callers.py  [modified]
  imports: -store.combine
  hunks: hunk@1-12 -> write_pair, write_two

ops.py  [added]
  symbols added:
    + def combine(a, b)
  module docstring touched
  hunks: hunk@1-5 -> combine

store.py  [modified]
  symbols removed:
    - def combine(a, b)
  signature changed: append
      old: def append(path, record)
      new: def append(path: str, record: Record, *, sync: bool=False) -> bool
      params +sync; annotations path,record; return annotation
  imports: +os
  module docstring touched
  hunks: hunk@1-9 -> top-level; hunk@13-25 -> append; hunk@28-30 -> top-level

cross-file view
  public added:   none
  public removed: none
  moves:          combine: store.py -> ops.py
  renames:        none

risk
  - signature of store.py:append changed; 3 call sites in this diff
  - combine moved store.py -> ops.py
```

That line about `PRSUMMARIZER_BASE_URL` is on stderr; the brief is on stdout, so
piping works. The exit code is 0.

`combine` left `store.py` and arrived in `ops.py` with the same parameters, so
it is reported as a move and not, twice over, as a removal plus an addition.
`append` is a public signature that widened, and the three places this diff
calls it are counted from the diff, not guessed.

Here is what the tool does when it cannot tell you something. This is a real
recent commit of this repository, and both files changed only inside functions,
so no reconstructable region parses on its own:

```
$ git diff ab236de~1 ab236de | .venv/bin/pr-summarizer
model not configured (PRSUMMARIZER_BASE_URL is not set); the structural brief does not need one
structural brief: 2 file(s) changed

src/pr_summarizer/cli.py  [modified]
  changed region does not parse; structural delta withheld
  hunks: hunk@87-93 -> not attributed; hunk@97-106 -> not attributed; hunk@109-115 -> not attributed
tests/test_cli.py  [modified]
  changed region does not parse; structural delta withheld
  hunks: hunk@9-16 -> not attributed; hunk@73-94 -> not attributed
cross-file view
  public added:   none
  public removed: none
  moves:          none
  renames:        none

risk
  - src/pr_summarizer/cli.py changed region does not parse; delta withheld
  - tests/test_cli.py changed region does not parse; delta withheld
```

The delta is withheld rather than guessed, and the hunks are not labelled
`top-level` either: an empty symbol map is not evidence that a hunk sits outside
every symbol. A diff shows changed regions and three lines of context, not whole
files, so a region with no parseable standalone start is reported as what it is.
The line stats and the hunk positions are still real.

## How it works

```
 diff text ............ stdin, a .diff path, or --git (which runs `git diff`)
    |
    v
 diff.parse ........... per file: paths, change type, hunks with line numbers
    |
    v
 ast_stage ............ symbol map of each hunk's new side, delta vs old side
    |
    v
 brief ................ one object: signatures, moves, renames, imports, risk
    |
    +-- model.summarize .... optional, one POST, brief in, prose out
    |
    v
 render .............. text (default) or json, then the exit code
```

Text and json are two renderings of the one `Brief` object, which is why the
human output and a machine consumer cannot end up describing different changes.
A non-Python file gets line counts and an explicit
`no structural analysis for this language` marker; the tool never fabricates a
parse it did not do.

## Requirements

- Python 3.12 or newer. Every command in this file ran on 3.13.5.
- `git`, only for `--git`; nothing else touches it.
- Nothing else. No database, no service, no client library.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

The `-e` is how this checkout is developed. The `[dev]` extra is pytest,
pytest-cov and ruff, and it is only needed to run the suite. Those two commands
ran verbatim in a copy of the tree and resolved pytest 9.1.1, pytest-cov 7.1.0,
coverage 7.16.1 and ruff 0.16.8 alongside the package, which pulls nothing
itself. That the package installs nothing else is the claim worth checking, so
both install forms were run here in throwaway venvs against `/tmp/ps-neutral-1`,
a copy of this tree with `.git` and `.venv` removed, so the transcripts below
carry a throwaway path and not a checkout. pip's build chatter is elided:

```
$ python3 -m venv /tmp/cr-ps-e
$ /tmp/cr-ps-e/bin/pip install -e /tmp/ps-neutral-1
...
Successfully built pr-summarizer
Installing collected packages: pr-summarizer
Successfully installed pr-summarizer-0.1.0
$ /tmp/cr-ps-e/bin/pip show pr-summarizer | grep -i requires
Requires:
$ /tmp/cr-ps-e/bin/python -c "import pr_summarizer; print(pr_summarizer.__version__)"
0.1.0
$ /tmp/cr-ps-e/bin/pip freeze
# Editable install with no version control (pr-summarizer==0.1.0)
-e /tmp/ps-neutral-1
```

An editable install is still pointed at a source tree, so a second venv took the
path a user takes:

```
$ python3 -m venv /tmp/cr-ps-f
$ /tmp/cr-ps-f/bin/pip install /tmp/ps-neutral-1
...
Successfully installed pr-summarizer-0.1.0
$ cd /tmp
$ /tmp/cr-ps-f/bin/pr-summarizer --no-model /tmp/ps-neutral-1/tests/fixtures/lifecycle.diff | head -4
structural brief: 4 file(s) changed

brand_new.py  [added]
  symbols added:
$ /tmp/cr-ps-f/bin/pip show pr-summarizer | grep -i requires
Requires:
$ /tmp/cr-ps-f/bin/pip freeze
pr-summarizer @ file:///tmp/ps-neutral-1
```

That `pip freeze` is one line and nothing else, and from `/tmp` the console
script and `import pr_summarizer` both resolve through that venv's
`site-packages`, with no source tree on any path.

## Usage

The diff comes from a path, from stdin, or from git:

```bash
.venv/bin/pr-summarizer tests/fixtures/shape.diff       # a .diff or .patch file
git diff HEAD~1 HEAD | .venv/bin/pr-summarizer          # stdin, the default
.venv/bin/pr-summarizer --git d68dd2f~1 d68dd2f         # runs `git diff` for you
```

`--git` takes every argument after it and hands the list to `git diff`, so a
range, two shas or a pathspec all work. The parser reads diff text only: it
never needs a working tree at the right commit, which is what lets it summarize
a fetched patch.

The machine view, for anything that wants to post process the result:

```
$ .venv/bin/pr-summarizer --no-model --format json tests/fixtures/shape.diff | head -14
{
  "cross_file": {
    "moves": [
      {
        "from": "store.py",
        "name": "combine",
        "to": "ops.py"
      }
    ],
    "public_added": [],
    "public_removed": [],
    "renames": []
  },
  "files": [
```

Output for an empty diff is not an error either:

```
$ .venv/bin/pr-summarizer --no-model tests/fixtures/empty.diff
structural brief: 0 file(s) changed

cross-file view
  public added:   none
  public removed: none
  moves:          none
  renames:        none

risk
  none
$ echo $?
0
```

## Flags

| Flag | Meaning |
|---|---|
| `path` | A `.diff`/`.patch` file. Omit to read the diff from stdin. |
| `--git ARG...` | Produce the diff with `git diff ARG...` instead of reading one. |
| `--format text\|json` | `text` is the default and for humans, `json` is the machine view. |
| `--no-model` | Never contact a model, even a configured one. |
| `--max-context BYTES` | Byte budget for the brief sent to the model. A byte count, not a token count. |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The brief was computed and printed. This includes no model configured. |
| 2 | Usage: the diff could not be read, or `git diff` failed. |
| 3 | The brief printed, but the model call failed. |

Code 3 is the interesting one. A model failure never replaces the brief on
stdout, because the brief is the tool's own work and it cost nothing to
compute. The failure is reported on stderr and carried in the exit code.

## Model access

Three variables, all read at call time:

| Variable | Meaning |
|---|---|
| `PRSUMMARIZER_BASE_URL` | Base URL of an OpenAI-compatible server, e.g. `https://api.openai.com/v1`. |
| `PRSUMMARIZER_MODEL` | Model name sent in the request. |
| `PRSUMMARIZER_API_KEY` | Bearer token. Unset means no `Authorization` header, which is what a local server wants. |

```bash
export PRSUMMARIZER_BASE_URL=http://127.0.0.1:8000/v1
export PRSUMMARIZER_MODEL=my-model
export PRSUMMARIZER_API_KEY='not-a-real-key'   # omit for a local server
.venv/bin/pr-summarizer tests/fixtures/shape.diff
```

The key is only ever placed in the `Authorization` header of the one request. It
appears in no message, no return value and no exception text, and no example here
carries anything key-shaped: an unset `PRSUMMARIZER_API_KEY` means no
`Authorization` header at all, which is what a local server expects.

What that looks like when nothing is listening on the port. The `export` form
above was run too, and this inline form is the transcript:

```
$ PRSUMMARIZER_BASE_URL=http://127.0.0.1:8000/v1 PRSUMMARIZER_MODEL=my-model \
    .venv/bin/pr-summarizer tests/fixtures/shape.diff
model error: cannot talk to the model endpoint (<urlopen error [Errno 111] Connection refused>); check PRSUMMARIZER_BASE_URL
structural brief: 3 file(s) changed
...
risk
  - signature of store.py:append changed; 3 call sites in this diff
  - combine moved store.py -> ops.py
$ echo $?
3
```

The `...` is the same brief body as in [The output](#the-output), elided here
because it is identical, 32 lines of stdout either way. A base URL with no scheme
gets the same treatment instead of a traceback, because that typo used to cost
the brief.

The request body is the rendered brief plus a short instruction to write an
architectural summary. It is never the raw diff; a test asserts the payload
contains no `diff --git` line. What is handed over is the text view, so the brief a
provider sees is the defused one: where a diff's own string literal carries a run
of backticks, the request carries that run with a backslash in front of it, one
character deeper than the file said, because `cli.py` sends what `render_text`
assembled and that body is what a fenced block is built from. The exact name is one
`--format json` away, and a test pins the marked form on the payload.

The brief is not neutral text either. Every name, path and signature in it was
written by whoever authored the diff, so a `Literal[...]` annotation in someone's
source code reaches the prompt as the parser rendered it. `build_request`
therefore frames it: the brief is delimited by `<structural-brief>` /
`</structural-brief>`, and the instruction says that what sits between them is
data describing a change, that its words came from the diff's author, and that
anything inside it reading as an instruction is content to report on, not a
direction to follow. The framed message, printed from a built request over
`tests/fixtures/empty.diff`:

```
$ .venv/bin/python -c "import json; from pr_summarizer import brief, model; cfg = model.Config.from_env({model.BASE_URL_ENV: 'http://127.0.0.1:8000/v1', model.MODEL_ENV: 'm'}); body = model.build_request(cfg, brief.render_text(brief.build(open('tests/fixtures/empty.diff').read())))[2]; print(json.loads(body)['messages'][1]['content'])"
<structural-brief>
structural brief: 0 file(s) changed

cross-file view
  public added:   none
  public removed: none
  moves:          none
  renames:        none

risk
  none
</structural-brief>
```

That is framing, not a wall. It reduces the surface: a line of diff-authored text
has to look like it belongs to the instruction region to be read as one, and now
it has to survive sitting inside a region that has been labelled data. It does
not neutralise the problem. A diff author can still write a string that imitates
the closing delimiter, or that reads plausibly as this tool's own prose, and a
model that acts on it produces a wrong summary in a pull-request comment. The
brief itself is computed without a model, so the tool's own output is never the
thing at stake. `tests/test_model.py::test_diff_authored_text_lands_inside_the_framed_region`
pins the placement: a `Literal['IGNORE PRIOR INSTRUCTIONS ...']` annotation from
the diff shows up inside the delimited region and never in the instruction
region. Whether a given model respects that framing has not been tested here; no
provider was contacted.

The claim about the payload was checked on the wire too, against a stdlib
`http.server` stub on loopback written for the purpose and left out of the tree.
With the frame in place it recorded 1,913 body bytes,
`diff_git_line_in_body: false`, and `auth_header_present: true`: the framed
brief, no diff header, and the presence of the header without its value, because
a value that is never written down cannot be echoed by the thing that logged it.
The same stub answers a 200 and a 401, which is how the real `urllib` transport
gets executed instead of replaced:

```
$ PRSUMMARIZER_BASE_URL=http://127.0.0.1:8917/v1 PRSUMMARIZER_MODEL=my-model \
    PRSUMMARIZER_API_KEY='not-a-real-key' \
    .venv/bin/pr-summarizer tests/fixtures/shape.diff | tail -5
  - combine moved store.py -> ops.py

model summary
----------------------------------------
Stub prose: combine moves out of store.py.
$ echo ${PIPESTATUS[0]}
0
```

```
$ PRSUMMARIZER_BASE_URL=http://127.0.0.1:8917/err PRSUMMARIZER_MODEL=my-model \
    PRSUMMARIZER_API_KEY='not-a-real-key' \
    .venv/bin/pr-summarizer tests/fixtures/shape.diff > /tmp/brief.txt
model error: model rejected the request (HTTP 401); check PRSUMMARIZER_API_KEY and PRSUMMARIZER_MODEL
$ echo $?
3
$ wc -l < /tmp/brief.txt
32
```

A 401 reaches `summarize` as an `HTTPError` from inside `urllib`, and the brief
still outlives it: 32 lines on stdout, the diagnosis on stderr, exit 3, no
token in either stream. A 200 appends the prose under a `model summary`
heading, which is the only place model text ever joins the output.

One property of `urllib` is worth naming for whoever supplies an endpoint: it
honours `http_proxy` and `https_proxy` from the environment, so a runner with a
proxy configured sends the model request through it. Measured here by pointing
`http_proxy` at a closed port and watching the failure move from an
unresolvable name to a refused connection.

Nothing in this repository has talked to a model provider, and nothing has sent
a byte to an address that is not loopback. Every test drives the transport seam
except two: one connects to a loopback port nothing listens on, and one hands
`urllib` a base URL with no scheme, which fails before a socket exists.

## GitHub Action

`action.yml` is a composite action: it checks the repository out with
`fetch-depth: 0`, installs the package, and runs the CLI over a revision range.
The brief lands in the job summary as a fenced block and in a `brief` output for
a caller to post as a comment.

That fence, and the one `.github/workflows/pr-summary.yml` puts around the same
text in a pull-request comment, is what `brief.fenced()` exists for. Both steps
write their block through it, so whatever a block wraps has its runs of backticks
defused on the way in. The guard sits at the block rather than upstream of it
because a fence does not only wrap the brief: what `action.yml` captures is the
CLI's stdout, which is the structural brief plus, when a model was configured and
answered, that model's prose. A response containing a line of three backticks
would otherwise close the step's own fence and have everything below it render as
markdown in a comment the bot authored.

The `brief` output is unchanged by all of that: it is the CLI's stdout byte for
byte, and the defusal is not baked into it. A caller that wraps those bytes in a
block is whoever writes that fence, and the block comes from the same helper.

The vector for the brief half of those bytes is the parser's own deliberate rule
about carriage returns: `diff.py` keeps a `\r` as part of a line rather than as a
line ending, so a patch whose header lines end CRLF renders a path with the CR
still attached, and CommonMark counts a lone CR as a line ending. A file named with
three backticks therefore puts a bare fence on a line of the brief. Reading GitHub's
own renderer out of the CommonMark rule is a reading: no comment body was rendered
here, and the checks below are against the rule, encoded in a script. `git diff`
writes its headers with LF, so the shape arrives as a fetched or hand-built patch:
the same diff text from stdin or a path that the tool documents it accepts.

Inside a fenced block CommonMark parses no inline code, no escapes and no
entities, so the only thing that can close the fence is a run of three or more
alone on a line. The defuse covers any run, not only runs of three, because the
same text is not only ever published inside a fence: on a terminal, and wherever a
reader pastes the brief as markdown, a run of one or two opens an inline code span
and is live. `render_text` applies the rule to the whole body it assembles, so a
backtick run from an annotation is marked before it reaches a block, and the
block's own pass skips a run that already carries a backslash instead of stacking
a second one onto it. The escape is applied to the text view only: `json.dumps`
escapes a carriage return, so the machine view cannot contain a fence line, and a
consumer of it needs the real file name.

The comment step no longer hands the body to `gh` through argv either; it writes
the fenced text under `RUNNER_TEMP` and passes `--body-file`. A command line is
readable by any other process on the runner for the life of the call, and the
body's length stops being the step's own business there; a file has neither
problem.

Model access is off unless both `model-base-url` and `model-name` are given, in
which case the step runs without `--no-model` and the brief leaves the runner.
That is the action's whole security story, and the second half of it is this: the
brief is made of names, paths and signatures taken out of the pull request, so
turning the model on hands text written by the PR's author to that endpoint,
framed as data. [Model access](#model-access) is what the framing does and does
not do. With no endpoint inputs set, the only thing the step sends anywhere is
the job summary the runner was always going to upload to GitHub.

```yaml
- uses: ./
  with:
    base: ${{ github.event.pull_request.base.sha }}
    head: ${{ github.event.pull_request.head.sha }}
```

`.github/workflows/pr-summary.yml` is that job plus a comment step, and is the
documented way to use the action.

GitHub has never run the action or either workflow. What was executed here is the
`brief` step's shell body, read out of `action.yml` with a scratch PyYAML script
(PyYAML is not a dependency of this package) and run in bash with `RUNNER_TEMP`,
`GITHUB_STEP_SUMMARY` and `GITHUB_OUTPUT` pointed at scratch files, over the range
`c7b6def..d68dd2f`: the second row of the table in
[ADR 0001](docs/adr/0001-ast-before-model.md), 45,919 diff bytes whose brief is
10,594. Both rows were produced again after the backtick escape went in, with the
same three counts, and the brief read back out of `$GITHUB_OUTPUT` then held no
backtick at all:

| Case | Step exit | `$GITHUB_STEP_SUMMARY` | `$GITHUB_OUTPUT` | `brief` value read back |
|---|---|---|---|---|
| no endpoint configured | 0 | 10,606 bytes | 10,647 bytes | 10,594 bytes, 127 lines |
| configured, port refused | 3 | 10,606 bytes | 10,647 bytes | 10,594 bytes, 127 lines |

Three counts, one brief: 10,594 bytes of stdout, plus 12 for the fence that wraps
it in the job summary, plus 53 for the `brief<<` heredoc delimiters in the output
file. Parsing that file back yields the brief byte for byte, which is what a
caller posting it as a comment gets. The second row is the same command with
`PRSUMMARIZER_BASE_URL=http://127.0.0.1:8000/v1` and a key in
`PRSUMMARIZER_API_KEY`, so `--no-model` is absent from the flags and the
connection is refused; no file under `RUNNER_TEMP` contained the key value
afterwards.

Both publish the brief and the second still reddens the job. That pairing is
deliberate: the step used to abort on the model failure before writing anything,
which meant the brief vanished exactly when it was most wanted.

The step publishes text. A caller that wants the machine view can add
`--format json` to the same flags array, and the plumbing carries it: that
variant ran here over the same range, wrote 32,312 bytes through the same
`$GITHUB_OUTPUT` heredoc, and `json.loads` on the value read back gives
`files_changed: 10` with the one withheld-delta risk entry intact.

The comment step ran here too. Its `run:` body was read out of the YAML with a
scratch script, executed in bash over a brief whose path line used to be a bare
fence, and the only thing stood in was `gh` itself: a script on `PATH` that
echoes the arguments it was handed, because `gh` is off-limits in this
environment (see [Limitations](#never-executed-and-what-each-one-would-prove)).
`BRIEF` is the render of a patch whose file name is three backticks and whose
header lines carry CR:

```
$ PATH=/tmp/fakebin:$PATH RUNNER_TEMP=/tmp PR_NUMBER=7 GITHUB_REPOSITORY=someone/whatever \
    GH_TOKEN=runner-provided BRIEF="$(.venv/bin/pr-summarizer /tmp/hostile.patch 2>/dev/null)" \
    bash /tmp/extracted-comment-step.sh
gh pr comment 7 --repo someone/whatever --body-file /tmp/pr-comment-body.md
$ .venv/bin/python /tmp/count-fences.py /tmp/pr-comment-body.md
bytes: 273
lines: 18
lines that can close the fence: [16]
```

Line 5 of that body is the hostile path with a backslash in front of its three
backticks, and line 16 is the closer the step itself writes. Measured on the same
input before the escape, the count came out `[5, 16]`: everything after line 5
rendered as markdown instead of as code. The scratch scripts, like the loopback
stub above, are not in the tree.

## Testing

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q --cov
```

Run here, on the tree this README describes:

```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/python -m pytest -q
96 passed in 0.88s
```

The first two also ran in a clean-room venv built by the block above, in a copy of
the tree with `.git` and `.venv` removed: `All checks passed!` and `91 passed in
0.52s`, with pytest 9.1.1 and ruff 0.16.8 resolved fresh, which is what CI's
`pip install -e ".[dev]"` pulls. That count is from the tree as it stood before
the request framing and the fence escape, and the clean room has not been rebuilt
since; the two tests added for those have run only in this checkout.

```
Name                             Stmts   Miss  Cover
----------------------------------------------------
src/pr_summarizer/__init__.py        2      0   100%
src/pr_summarizer/ast_stage.py     304     10    97%
src/pr_summarizer/brief.py         215      8    96%
src/pr_summarizer/cli.py            54      0   100%
src/pr_summarizer/diff.py          161      0   100%
src/pr_summarizer/model.py          83      5    94%
----------------------------------------------------
TOTAL                              819     23    97%
```

Six test modules. The corpus is in `tests/fixtures/`, seven `.diff` files that
are the literal byte output of `git diff` run against scratch repositories, each
one there for a construct the parser has to survive: adds, deletes, a rename
carrying a `similarity index`, a mode-only change with no hunks, a CRLF file with
a `\ No newline at end of file` marker, a change that leaves the new file
unparseable, a diff touching nothing. None of them was typed by hand.

Two tests carry diff text of their own instead, and say so where they are: the
annotation in `tests/test_model.py` and the CRLF patch in `tests/test_brief.py`.
Neither is a shape the parser has to survive, which is what `tests/fixtures/` is
for, and neither could be produced by `git diff`: no provider writes the hostile
`Literal[...]` into a file for you, and git ends its header lines with LF.

The suite needs no network, no endpoint and no key. Model access is driven
through an injectable transport; the two exceptions are a loopback connect to a
port nothing listens on and a base URL with no scheme, which is where `urllib`
fails before a socket exists.

## Limitations

The state of the evidence, not a disclaimer.

### Executed here

Lint and the full suite, in this checkout and again in a clean-room venv built
by `pip install -e ".[dev]"`. Two clean-room installs of the package alone, one
editable and one not, each with an empty `Requires:` field and a console script
that runs from outside the source tree. Every CLI transcript on this page,
produced by the command shown above it, including the exit codes: 0 for a
computed brief and for no model configured, 2 for an unreadable path and for a
`git diff` that fails, 3 for every model failure. Repeat-run determinism,
compared byte for byte between `python -m pr_summarizer.cli` and the installed
console script, plus three runs of one fixture with the same checksum. The
action's shell body, in bash, with and without a configured endpoint, and again
with `--format json` so the value in `$GITHUB_OUTPUT` could be parsed rather than
eyeballed. The workflow's comment step, in bash, over a brief whose path line used
to be a bare fence, with `gh` stood in by a script that echoes its arguments and
with the file it wrote counted rather than read. The real `urllib` transport,
against a loopback stub: a 200 with an
OpenAI-shaped body and a 401, and the framed request body measured again after the
frame went in. Every failure path a machine can produce without a provider: a
refused port, an unresolvable host, a schemeless base URL, and a proxy in the
environment.

### Never executed, and what each one would prove

| Thing | What is unproven |
|---|---|
| `action.yml` | GitHub has never run it. Only the step's shell body ran here, in bash, with the runner variables pointed at scratch files. Its `pip install "$GITHUB_ACTION_PATH"` was reproduced in the same non-editable form against a copy of the tree; `fetch-depth: 0`, the `inputs.*` context expressions and the resolution of `uses: ./` have never been interpreted by anything. |
| `.github/workflows/ci.yml` | Never run. `actionlint` is not installed here and cannot be. Its three `run:` lines were each executed by hand, in the clean-room venv for the install one, and the YAML parses. |
| `.github/workflows/pr-summary.yml` | Never run by GitHub. Its comment step's `run:` body did run here, in bash, but the `gh` it reached was a script on `PATH` that echoes its arguments: `gh` is deliberately off-limits in this environment, so no comment was ever sent and `--body-file` was never read by anything that would post it. Nothing about the step's `env:` interpolation or the runner's `RUNNER_TEMP` lifetime has been interpreted by GitHub. |
| A live model provider | No provider was contacted, so a real one's error bodies, rate limits and any status the tool does not name are exercised against fake transports only. It also means the request framing is unproven where it matters: the suite asserts that the delimited region carries the diff's words and that the instruction region does not, which is a claim about bytes this tool builds, not about how a server reads them. Nobody has shown a framed brief to a model from here. The two returns inside `_urllib_transport` are coverage misses (`model.py` 121 and 123) because the suite replaces that transport; both did run here, against a loopback stub that is deliberately not in the tree, so reproducing that evidence means writing the stub again. The other three misses are ordinary gaps in the test inputs: 169 wants a status outside the four the tool names, and 183 and 186 want a brief that already fits its budget or a budget that is not positive. |
| Python 3.12 | `requires-python = ">=3.12"` and the CI matrix both claim it. Everything here ran on 3.13.5. Nothing in the code uses a 3.13-only construct, and that is a reading of the source, not a run. |
| A pull request from a fork | `pr-summary.yml` passes `pull_request.head.sha` to `git diff`. On a forked PR that object may not exist in the checked-out history even at `fetch-depth: 0`, so the step would fail in `git diff` with exit 2. Not tested; needs a second repository. |

### Behaviour that is what it is

- The supported input is git's dialect of unified diff. A patch from GNU
  `diff -u`, which has no `diff --git` header, parses to
  `0 file(s) changed` and exits 0. Measured, not hypothesized.
- A hunk that opens and closes inside a function yields no symbol delta, only
  line stats and positions. That is most small edits to existing code, and it is
  the price of parsing diff fragments instead of holding a checkout, which the
  spec's input contract requires.
- Python only. YAML, Markdown, shell and JSON get line counts and a marker.
- Every run of backticks in the text view is preceded by a backslash, and the
  json view carries the path unchanged. The defusal a published block depends on
  is `brief.fenced()`, at the fence; `render_text` applies the same rule to what it
  assembles, so it holds on a terminal too: a path whose name is three backticks
  prints with a backslash in front of them. Altered, never hidden, and
  `--format json` is the view to read when the exact name matters.
- `--format json`'s `hunks[].inside` is `[]` for both a genuinely top-level
  hunk and one whose file was withheld. Read the file's `parsed` and `untrusted`
  fields to tell them apart; the text rendering spells the difference out.
- Rename detection pairs a removed symbol with an added one of the same kind and
  the same parameter list. It is printed as `(inferred)` because that is also
  what a coincidental extraction looks like.
- No linting, no style opinions, no line-by-line commentary. The unit of summary
  is the symbol.

## License

[MIT](LICENSE). © 2026 Shayan Golmezerji.
