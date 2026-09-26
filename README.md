# pr-summarizer

Structural summaries of a pull-request diff, computed with the standard
library's `ast`.

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

No CI badge: `ci.yml` was green on each of the four runs it had through
2026-09-26, and the workflow that drives this repo's own action went red at
`uses: ./` on 2026-09-23 (run 35934850926) and, once the checkout fix landed,
green end to end on 2026-09-26 (run 36257122799), so a badge on the test job
alone would be a claim about both.
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
both install forms were run here in throwaway venvs against `/tmp/ps-neutral-2`,
a copy of this tree, `tools/` included, with `.git`, `.venv`, `.coverage` and
the caches left out, so the transcripts below carry a throwaway path and not a
checkout. pip's build chatter is elided:

```
$ python3 -m venv /tmp/cr-ps-e2
$ /tmp/cr-ps-e2/bin/pip install -e /tmp/ps-neutral-2
...
Successfully built pr-summarizer
Installing collected packages: pr-summarizer
Successfully installed pr-summarizer-0.1.0
$ /tmp/cr-ps-e2/bin/pip show pr-summarizer | grep -i requires
Requires:
$ /tmp/cr-ps-e2/bin/python -c "import pr_summarizer; print(pr_summarizer.__version__)"
0.1.0
$ /tmp/cr-ps-e2/bin/pip freeze
# Editable install with no version control (pr-summarizer==0.1.0)
-e /tmp/ps-neutral-2
```

An editable install is still pointed at a source tree, so a second venv took the
path a user takes:

```
$ python3 -m venv /tmp/cr-ps-f2
$ /tmp/cr-ps-f2/bin/pip install /tmp/ps-neutral-2
...
Successfully installed pr-summarizer-0.1.0
$ cd /tmp
$ /tmp/cr-ps-f2/bin/pr-summarizer --no-model /tmp/ps-neutral-2/tests/fixtures/lifecycle.diff | head -4
structural brief: 4 file(s) changed

brand_new.py  [added]
  symbols added:
$ /tmp/cr-ps-f2/bin/pip show pr-summarizer | grep -i requires
Requires:
$ /tmp/cr-ps-f2/bin/pip freeze
pr-summarizer @ file:///tmp/ps-neutral-2
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

The fixtures were held to the same rule and one revision of them missed it. The
first commits of `tests/test_cli.py` and `tests/test_model.py` used
`sk-fake-not-a-real-key-0123456789`, which announces itself as a placeholder and
is still shaped like a key. Those blobs are in this repository's history, so the
sentence is here rather than a rewrite. Both files now use
`not-a-real-key-0123456789`. Nothing else key-shaped exists in any object in this
repository, checked across every blob, tree and commit rather than the working
trees alone, and no credential has ever been committed here.

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

The brief is not neutral text either. Its names, paths and signatures come out of
the code the diff touches, so a `Literal[...]` annotation in someone's source
reaches the prompt as the parser rendered it, and where a symbol was only removed
or a rename inferred, the words are whoever wrote them earlier rather than whoever
deleted them. `build_request` therefore frames it: the brief is delimited by
`<structural-brief>` / `</structural-brief>`, and the instruction says that what
sits between them is data describing a change, that its words were written by
whoever wrote the diff, and that anything inside it reading as an instruction is
content to report on, not a direction to follow. The framed message, printed from a
built request over `tests/fixtures/empty.diff`:

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
the fenced text under `RUNNER_TEMP` and passes `--body-file`. The two reasons that
hold are size and fidelity: as one argument the body counts against the runner's
`ARG_MAX`, which that limit shares with the environment block, and text carried
through a shell substitution loses its trailing newlines. What did not change is
the exposure, which moved rather than shrank. argv was readable by any other
process on the runner for the life of the call; the file is readable for the life
of the step, and a `gh` that failed used to leave it behind for the rest of the
job. The step now removes it on its way out, trap and all, so both runs reported
below found no body file in `RUNNER_TEMP` afterwards whatever `gh` did. A shorter
window, not a closed one.

Model access is off unless both `model-base-url` and `model-name` are given, in
which case the step runs without `--no-model` and the brief leaves the runner.
That is the action's whole security story, and the second half of it is this: the
brief is made of names, paths and signatures taken out of the pull request, its
author's own words where they wrote code and somebody else's where the diff only
removed it, so turning the model on hands text the PR carried to that endpoint,
framed as data. [Model access](#model-access) is what the framing does and does
not do. With no endpoint inputs set, the only thing the step sends anywhere is
the job summary the runner was always going to upload to GitHub.

```yaml
- uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
  with:
    fetch-depth: 0
- uses: ./
  with:
    base: ${{ github.event.pull_request.base.sha }}
    head: ${{ github.event.pull_request.head.sha }}
```

That first line is not decoration. A runner locates a local action in the
workspace before any of its steps run, so `uses: ./` cannot resolve until
`action.yml` is already on disk, and the checkout inside the action happens
after it was found and started. The `fetch-depth: 0` is not decoration either:
the action is handed the PR's base sha, and a default checkout brings down one
commit. Deepening a shallow clone afterwards was tried here and does not
happen, a depth-less `git fetch` on git 2.47.3 left the repository at one
commit and still shallow, so the history has to be complete at the first
clone. That is the caller's checkout, not the action's.

`.github/workflows/pr-summary.yml` is those two steps plus a comment step, and is
the documented way to use the action.

The action has now run a step on GitHub. The first attempt, a run of
`pr-summary.yml` on a Dependabot pull request, stopped at the first step with
`Can't find 'action.yml', 'action.yaml' or 'Dockerfile'`: that workflow had no
checkout, which is what the two lines at the top of the snippet above now
supplies. The proof of that fix is not local: when the same pull request
re-synced on top of it, GitHub ran the workflow end to end (run 36257122799,
2026-09-26, success), every step of the action came back green, and the comment
step's real `gh` posted the brief to pull request #1. What was executed here,
before any of that, is the `brief` step's shell body, read out of
`action.yml` with `tools/step_body.py` and run in bash with `RUNNER_TEMP`,
`GITHUB_STEP_SUMMARY` and `GITHUB_OUTPUT` pointed at scratch files, over the
range `c7b6def..d68dd2f`: the second row of the table in
[ADR 0001](docs/adr/0001-ast-before-model.md), 45,919 diff bytes whose brief is
10,594. Both rows were produced again after the backtick escape went in, with the
same three counts, and that pairing is a no-change regression check rather than
evidence about the escape: this range's brief holds no backtick at all, counted in
`$RUNNER_TEMP/pr-brief.txt` and again in the value read back out of
`$GITHUB_OUTPUT`, so on this input the escape changes nothing. What the escape does
is measured below, on the input the comment step ran over.

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

The comment step ran here too. Its `run:` body came out of the workflow with
`tools/step_body.py` and was executed in bash over a brief whose path line used to
be a bare fence, and the only thing stood in was `gh` itself: `tools/stub-bin/gh`,
a script on `PATH` that echoes the arguments it was handed, because `gh` is
off-limits in this environment (see
[Limitations](#not-executed-here-and-what-each-one-would-prove)). It copies whatever
`--body-file` names to `GH_STUB_COPY`, outside `RUNNER_TEMP`, so the body that was
handed over can be counted after the step's own `trap` has deleted the original.
`BRIEF` is the render of `tools/hostile_patch.py`'s patch, whose one file is named
with three backticks and whose header lines carry CR:

```
$ mkdir -p /tmp/prfence
$ .venv/bin/python tools/hostile_patch.py /tmp/prfence/hostile.patch
wrote /tmp/prfence/hostile.patch: 100 bytes
$ .venv/bin/python tools/step_body.py .github/workflows/pr-summary.yml \
    "Comment on the pull request" /tmp/prfence/comment-step.sh
wrote /tmp/prfence/comment-step.sh: 1120 bytes
$ PATH="$PWD/tools/stub-bin:$PWD/.venv/bin:$PATH" RUNNER_TEMP=/tmp/prfence \
    PR_NUMBER=7 GITHUB_REPOSITORY=someone/whatever GH_TOKEN=runner-provided \
    GH_STUB_COPY=/tmp/prfence/body.md \
    BRIEF="$(.venv/bin/pr-summarizer --no-model /tmp/prfence/hostile.patch 2>/dev/null)" \
    bash /tmp/prfence/comment-step.sh
gh pr comment 7 --repo someone/whatever --body-file /tmp/prfence/pr-comment-body.md
$ ls /tmp/prfence
body.md
comment-step.sh
hostile.patch
$ .venv/bin/python tools/count_fence_lines.py /tmp/prfence/body.md
bytes: 273
CommonMark lines: 17
lines that can close a fence: [17]
```

Every line number here is a CommonMark line, the one convention
`tools/count_fence_lines.py` counts by and prints under that name. A lone carriage
return ends a line, and that is what gives the hostile path's run a line to
itself; the same 273 bytes are 16 lines to `wc -l`, and the two are not comparable.
Line 3 opens the block, line 6 is that run carrying a backslash in front of it,
line 7 is the `  [modified]` the carriage return left behind, and line 17 is the
closer the block helper wrote: the body's last line, and the only one that can close
the fence.

The body holds exactly one backslash, and it is the escape's. Take that byte back
out and the same command shows what the byte was for:

```
$ tr -dc '\\' < /tmp/prfence/body.md | wc -c
1
$ tr -d '\\' < /tmp/prfence/body.md > /tmp/prfence/no-escape.md
$ .venv/bin/python tools/count_fence_lines.py /tmp/prfence/no-escape.md
bytes: 272
CommonMark lines: 17
lines that can close a fence: [6, 17]
```

Read that against the rule, not a render: line 6 is now a bare run of three, so it
closes the block opened at line 3, lines 7 through 16 render as markdown instead of
as code, and the closer at line 17 opens a fence nothing closes. One byte is the
difference. What was measured here and what was not stay separate: `[6, 17]` is a
count of a body the current code wrote with one character taken back out of it.
The pre-escape code was never checked out and run.

All four scripts this passage used are in the tree: `tools/hostile_patch.py`,
`tools/step_body.py`, `tools/count_fence_lines.py` and `tools/stub-bin/gh`. The
loopback model stub under [Model access](#model-access) is not, so reproducing that
evidence means writing the stub again.

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
103 passed in 0.87s
```

The first two also ran in a clean-room venv, built by the two commands under
[Installation](#installation) in a copy of the tree with `.git`, `.venv`,
`.coverage` and the caches left out, whose remaining file set is exactly the tracked
one: `All checks passed!` and `103 passed in 0.48s`, the same count as here, on
CPython 3.13.5 with pytest 9.1.1 and ruff 0.16.8 resolved fresh. `ruff check .`
walked the same 17 files in the copy as here, the three scripts under `tools/`
included, so those are covered by the command CI runs and not by reading its config.
The copy keeps `tools/stub-bin/gh` executable, which is the mode the index stores and
what the comment step above needs, and no test opens that file, so a stub that lost
its exec bit would fail that transcript and leave `pytest` green. `Requires:` is
empty and the installed console script answers `--help` with exit 0 from outside the
source tree.

What the checkout cannot show: three of `tests/test_fence_publication.py`'s
structural tests read `action.yml` and `.github/workflows/` from the repo root, so a
smaller copy is not a smaller version of this run. With those two paths taken out,
`ruff check .` still passed and the three failed on `FileNotFoundError` rather than
skipping. The coverage table below is from this checkout, where `--cov` was run again
against the current tree; it did not run in the clean room.

```
Name                             Stmts   Miss  Cover
----------------------------------------------------
src/pr_summarizer/__init__.py        2      0   100%
src/pr_summarizer/ast_stage.py     304     10    97%
src/pr_summarizer/brief.py         217      8    96%
src/pr_summarizer/cli.py            54      0   100%
src/pr_summarizer/diff.py          161      0   100%
src/pr_summarizer/model.py          83      5    94%
----------------------------------------------------
TOTAL                              821     23    97%
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

### Not executed here, and what each one would prove

| Thing | What is unproven |
|---|---|
| `action.yml` | GitHub ran its steps green in run 36257122799, 2026-09-26: `uses: ./` resolved, the action's own checkout ran at `fetch-depth: 0`, `pip install "$GITHUB_ACTION_PATH"` built the wheel and installed `pr-summarizer-0.1.0`, and the `brief` step's output reached the pull request as a comment. What has not run there: the model-configured path, because the repository sets no `PRSUMMARIZER_BASE_URL` var, so the step took `--no-model`; a provider, and a non-empty key input, remain unexecuted combinations on a runner. Before any of that, what ran here was the step's shell body, in bash, with the runner variables pointed at scratch files, and its `pip install "$GITHUB_ACTION_PATH"` was reproduced in the same non-editable form against `/tmp/ps-neutral-2`, the copy the Installation transcripts ran from. Runner output at `uses: ./`: 35934850926 answered `Can't find 'action.yml'` and started nothing, which is the fact the caller's own checkout step rests on; 36257122799 started everything. |
| `.github/workflows/ci.yml` | Green on every run of it through 2026-09-26: 35934782328 and 36256982429 off `main`, 35934851117 and 36257122821 on the pull request. That is the test job only, and it covers neither of the other two files. `actionlint` is not installed here and cannot be. Its three `run:` lines were each executed by hand, in the clean-room venv for the install one, and the YAML parses. |
| `.github/workflows/pr-summary.yml` | Ran twice through 2026-09-26, both times on the same Dependabot pull request. Run 35934850926 failed at the `uses: ./` step for want of a checkout, the runner having answered `Can't find 'action.yml'`. Run 36257122799, on that same pull request re-synced after `9d6a0da` put the checkout ahead of `uses: ./` on `main`, ran and passed every step: the step's `env:` interpolation and its `RUNNER_TEMP` body file were interpreted by the runner, and the real `gh` posted `pull/1#issuecomment-5848081676`. What no runner has executed: the model branch, and a pull request from a fork. The comment step's `run:` body had also run here first, in bash, but the `gh` it reached was `tools/stub-bin/gh`, a script on `PATH` that echoes its arguments, because `gh` is deliberately off-limits in this environment: no comment was ever sent from this machine, and here `--body-file` was read by nothing that would post it. |
| A live model provider | No provider was contacted, so a real one's error bodies, rate limits and any status the tool does not name are exercised against fake transports only. It also means the request framing is unproven where it matters: the suite asserts that the delimited region carries the diff's words and that the instruction region does not, which is a claim about bytes this tool builds, not about how a server reads them. Nobody has shown a framed brief to a model from here. The two returns inside `_urllib_transport` are coverage misses (`model.py` 124 and 126) because the suite replaces that transport; both did run here, against a loopback stub that is deliberately not in the tree, so reproducing that evidence means writing the stub again. The other three misses are ordinary gaps in the test inputs: 172 wants a status outside the four the tool names, and 186 and 189 want a budget that is not positive or a brief that already fits it. |
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
