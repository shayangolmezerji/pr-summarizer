# ADR 0001: A structural brief before the model, on the standard library only

## Status

Accepted. 2026-09-23.

Split the claims in this record before believing it. Executed on this machine,
on Python 3.13.5: the byte counts in the table, the repeat-run check, the
clean-room install, the two `pip install` closures, and the 91 tests over the
seven-fixture corpus. Read and argued, never executed: everything about what a
language model does with a brief rather than a raw diff. No provider was
contacted from here and no endpoint answered one, so nobody watched a model do
either job. `action.yml` and the two workflows in `.github/workflows/` have
since been run by GitHub: `ci.yml` was green on each of the four runs it had
through 2026-09-26, and `pr-summary.yml` failed its first, run 35934850926, at
`uses: ./` for want of a checkout, then passed run 36257122799 once `9d6a0da`
added one, every step of the action included.
What was run here, before any of that, is the action's shell body extracted
from the YAML and executed against scratch files.

## Context

The tool reads a pull-request diff and says what changed about the shape of the
code. Two readers matter: a human in a review, and a language model asked to
turn the result into prose. The second is optional. The first is why the tool
exists.

The plumbing question at the start was whether the AST stage earns its keep at
all. A model has a context window, the diff is already there, and forwarding it
is one fewer stage to build and to be wrong about. The answer is that a diff and
a brief are not the same size and, more to the point, not the same information.

Measured on this repository's own history, diff bytes against the bytes the
brief renders for the same range:

| Range | what it is | diff | brief | ratio |
|---|---|---|---|---|
| `6b1b705..d68dd2f` | everything after the scaffold commit, 2,592 diff lines over 21 files, most of them Python added whole | 90,348 B | 20,074 B | 4.5x |
| `c7b6def..d68dd2f` | the last three commits, 1,306 lines, two modules added and one edited | 45,919 B | 10,594 B | 4.3x |
| `d68dd2f~1..d68dd2f` | one commit adding three YAML files, 174 lines | 5,952 B | 443 B | 13.4x |

Read those numbers for what they are. The two around 4x are ranges dominated by
added Python files, where the brief has to list every symbol once: that is the
compression the AST stage actually buys. The 13.4x row is not a compression
figure at all, it is a commit whose three files are YAML, where the brief is
short because the tool reports line counts and refuses the rest.

The size argument is the weaker half anyway. A diff says `+def append(path,`,
which is a line. It does not say that a public signature widened, that this
diff calls it in three places, or that a helper left one module and arrived in
another. Those are the lines the brief renders:

```
risk
  - signature of store.py:append changed; 3 call sites in this diff
  - combine moved store.py -> ops.py
```

Getting them means holding the new side of each hunk and parsing it, which is
work a model can be asked to do over the 2,592 lines the first table row shows
but which has an exact answer here and no exact answer there. A model handed the
raw diff spends its budget re-describing lines that are obviously present, and
the callsite count it gives you is a guess. This is the claim about model
behaviour in this record, and it is the one part no command on this machine
tested.

## Decision

Compute the change's shape with the standard library's `ast` before any model is
consulted, and hand the model that brief and nothing else. Ship the whole thing
with zero runtime dependencies.

The AST stage reconstructs the new side of each hunk from the diff text and
parses that, never the working tree, so it runs on a fetched patch with no
checkout. A region that will not parse makes the file untrusted and the delta is
withheld rather than guessed: from a failed parse you cannot conclude a symbol
was removed. That path is not hypothetical, it fired on this repository's own
history during the work that produced this record: `pr-summarizer --git c7b6def
d68dd2f` reports `src/pr_summarizer/ast_stage.py` as untrusted and withholds its
delta, and renders everything else in the range. Renames are paired by shape and
labelled `(inferred)` in the output, because same-kind-same-parameters is what a
rename looks like in a diff and is also what a coincidental extraction looks
like.

Model access is one `urllib.request` POST to an OpenAI-compatible
`chat/completions` address, with base URL, model name and bearer token from the
environment. No model configured is the default path, not a fallback: the brief
is the work product and the model is a renderer bolted onto it. When a model is
configured and fails, the brief still prints and the failure rides in the exit
code, because a run that prints nothing wastes the parse it already did.

`dependencies` is empty, and that includes the model call.

## Consequences

What it buys:

- The brief is one data object with two renderings, so the text a human reads
  and the json a caller consumes cannot disagree about what changed. The test
  `test_text_and_json_describe_the_same_change` asserts the pairing.
- The output is reproducible in a way a model's is not. Two runs over the same
  fixture with `--no-model`, one through `python -m pr_summarizer.cli` and one
  through the installed console script, produced byte-identical output here
  (`cmp` clean). A comment a caller posts can therefore be re-derived later and
  will match.
- Installing is this package and nothing else. Verified by a clean-room
  `python3 -m venv /tmp/cr-ps-a && /tmp/cr-ps-a/bin/pip install -e .`: the
  `Requires:` field of `pip show` came back empty and `pip freeze` listed only
  this package.

What it costs, and the part of it this repo accepted on purpose:

- **A hand-rolled unified-diff parser.** 161 statements in
  `src/pr_summarizer/diff.py`, statement coverage 100% from the fixture corpus.
  The exposure is a diff shape the corpus does not contain, and it fails by
  silence rather than by error: measured here, a patch produced by GNU `diff -u`
  (no `diff --git` header) parses as `structural brief: 0 file(s) changed` and
  exits 0. The supported input is git's dialect of unified diff, and anything
  else reads as an empty diff.
- That risk is bounded by where the fixtures come from. Each of the seven is
  literal `git diff` output captured from a scratch repository, not typed by
  hand, and each exists for constructs the parser has to survive: added and
  deleted files, a rename with a `similarity index`, a mode-only change with no
  hunks, a CRLF file with a `\ No newline at end of file` marker, a change that
  leaves the new file unparseable, a diff touching nothing, and one diff where
  Python and non-Python files mix. Branches in the parser exist because one of
  those needed it. A new shape enters as a new fixture produced by running git,
  which is the discipline that keeps a hand-written parser from drifting into
  speculation.
- Python only. Any other language gets line counts and an explicit marker, and
  the tool never fabricates a parse it did not do.
- `urllib` means no retries, no streaming, no proxy handling, one fixed 60
  second timeout, four status branches, and one catch for a call that never got
  an answer at all. Error messages name the environment variable that is
  probably wrong instead of relaying a provider's text, and the bearer token
  appears in no message and in no return value.
- That catch is the cost showing up early, twice. A refused port came first: it
  surfaced as a raw traceback, exit 1, no brief, and nothing caught it, because
  `URLError` is an `OSError` and only `HTTPError` was handled. A base URL typed
  without a scheme came second, raising `ValueError` inside `Request()` before a
  socket existed, which the first fix did not cover. Both are caught now, one
  test against a loopback port nothing listens on and one against a
  schemeless URL, and the shape of the bug is the honest argument against the
  typed exceptions an SDK would have handed back.

## Rejected alternatives

**A provider SDK (`openai`, or `httpx` directly).** Measured on this machine
today: `pip install openai` into an empty venv resolved 14 packages, including
a pydantic and an httpx. The request this tool makes is one POST with a JSON
body and a bearer header, assembled by `build_request` in `model.py`. What the
SDK gives up by being rejected: retries, streaming, typed exceptions, proxy
handling. What it would have cost: `dependencies` stops being empty, and the
runners this tool is aimed at include ones that cannot reach a registry at all.
Losing the optional renderer is better than losing the brief.

**A diff-parsing library.** `pip install unidiff` into an empty venv is one
package with no dependencies, so this rejection is not about dependency
closure and pretending otherwise would be padding. It is about who owns the
parse when a real pull request breaks it. The constructs this tool needs are
git's extensions and the hunk line numbering the AST stage is built on: rename
and mode metadata, similarity percentage, a binary block that must not be
parsed, and the boundary rule that stops a file whose last line has no newline
from swallowing the next file's `index` header. A generic parser normalises
those away or models them differently, and the fix would be an upstream issue
filed while a review waits. The trade taken instead is 161 statements plus the
fixture corpus, both owned here.

**A local llama.cpp or ollama as the default.** Recorded as the substitution for
this project in the portfolio plan it was built from. Consequences if taken:
installing the tool becomes downloading weights, the deterministic brief gets
conflated with a renderer that may not be present, and the tool stops working on
a runner with no model on disk. The environment-variable design gets the useful
half of it: any server that speaks the chat-completions shape works, a local one
included, without the package assuming a server exists or knowing which one it
is. Not run here: no local inference server was started, so that path is stated,
not demonstrated.

**A larger context window instead of the AST stage.** Costs the bytes measured
above, and costs the determinism: a model re-summarising the same diff twice
gives two wordings, so the brief could not be the artifact a reviewer quotes,
and the suite could not assert anything about it. The tests are written against
the structural brief for exactly that reason, which is how a 91-test suite runs
in under half a second with no network. This is also the alternative whose
premise this machine could not check: the argument that a model reviews shape
better when handed shape is reasoning about model behaviour, not a result.

**Reading the working tree instead of the diff text.** Needs a checkout at the
right commit, which the Action would have to arrange and a caller piping a
patch could not provide, and makes "what changed" depend on files the diff never
mentions. `docs/spec.md` fixes the input as diff text, and the parser holds to
it.
