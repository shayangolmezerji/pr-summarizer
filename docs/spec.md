# Spec: pr-summarizer

Turns a pull-request diff into a structural brief about what changed in the
code's shape, and optionally hands that brief to a language model for prose.

The brief is the product. The model is an optional renderer on top of it. The
tool is useful with no model configured, and the brief is what every test is
written against.

## Why an AST stage at all

A model handed 4,000 lines of raw diff reviews the lines. It re-describes code
that is obviously there and misses the change that matters, because the signal
it needs is buried in `+`/`-` noise. A model handed a structural brief reviews
the change: which functions appeared or vanished, whose signature moved, what
crossed files. The AST stage exists for that context economy, and it is
deterministic, so the same diff always yields the same brief. The reasoning is
in `docs/adr/0001-ast-before-model.md`.

## Input

A unified diff, from exactly one of:

- standard input (the default when no path is given),
- a `.diff` / `.patch` file passed as a positional path,
- a `git diff` range the tool produces by running `git` (`--git RANGE`),
  where RANGE is any argument `git diff` accepts.

The parser reads the diff text alone. It does not need a working tree, so the
Action can feed it a fetched patch.

## Pipeline

```
 diff text
    |
    v
 diff.parse ................... per-file: old/new path, change type, hunks
    |
    v
 ast.stage (Python files) .... symbol map of the NEW content
    |                          delta against the OLD content
    v
 brief ....................... deterministic structure, no model
    |
    +---> text / json render  (exit here with no model configured)
    |
    v
 model.summarize (optional) .. brief + short instruction -> prose
```

## Output contract

Before any model: a `Brief`, one entry per changed file, each with

- `path`, `change_type` (added, deleted, renamed, modified, mode-only),
- symbols added, removed, renamed, and moved to or from another file,
- signature changes: parameters, defaults, annotations, return annotation,
- decorators added or dropped,
- module docstring present/absent change, and `__all__` touched,
- imports added or removed,
- each hunk tagged with the symbol it lands inside, or `top-level` when it
  lands outside every symbol,
- a one-line risk read, e.g. "signature of store.append changed; 3 call sites
  in this diff".

Two renderings of the same structure: `--format text` (default, human) and
`--format json` (the Action). Byte-for-byte deterministic for a given input.

Non-Python files get hunk-level line counts and an explicit
`"no structural analysis for this language"` marker. The tool never fabricates
a parse it did not do.

## AST-stage guarantees

- Parses the NEW file content reconstructed from the diff, not the working tree.
- A file that will not parse as Python is reported as unparseable, not guessed
  at; its hunks still get line stats.
- Symbol line ranges come from `ast` node positions, so a hunk is attributed to
  the symbol that lexically contains it.
- Rename detection pairs a removed symbol with an added one of a similar
  signature in the same file; it is a heuristic and is labeled as such in the
  brief, never presented as certain.
- Everything the brief asserts is computed from the diff. Nothing is inferred
  about code the diff does not touch.

## Model access

`pr_summarizer/model.py` POSTs to an OpenAI-compatible `chat/completions`
endpoint through stdlib `urllib.request`, behind an injectable transport so
tests never open a socket.

| Variable | Meaning |
|---|---|
| `PRSUMMARIZER_BASE_URL` | Base URL, e.g. `https://api.openai.com/v1`. |
| `PRSUMMARIZER_MODEL` | Model name sent in the request. |
| `PRSUMMARIZER_API_KEY` | Bearer token. Absent means no auth header. |

The request body is the rendered brief plus a short instruction to write an
architectural summary. It is not the raw diff.

No local llama.cpp dependency and no provider SDK. Base URL and model name from
the environment mean any OpenAI-compatible server works, including a local one,
without the tool shipping or assuming a client library. This is the substitution
`PLAN.md` records for Project Gamma.

Missing configuration is not an error: the tool prints the structural brief and
exits 0 with a printed reason naming which variable is unset. A 401, 404 or 429
surfaces as an error naming the environment value that is probably wrong, and
never prints the key.

## CLI

`pr-summarizer [PATH]`, subcommand-free. Flags:

- `--git RANGE` to source from a git range instead of stdin or a path,
- `--format text|json`,
- `--no-model` to skip model access even when configured,
- `--max-context BYTES` to cap the brief sent to the model. It is a byte budget,
  named for what it measures; it is not a token count.

## Non-goals

- No linting. Ruff exists; this does not duplicate it.
- No style opinions. The brief reports shape, not taste.
- No line-by-line commentary. The unit of summary is the symbol.
- No provider SDK. One `urllib` call keeps the install dependency-free.
- No working-tree mutation, no network except the one model call.
- Zero runtime dependencies, enforced in `pyproject.toml`.
