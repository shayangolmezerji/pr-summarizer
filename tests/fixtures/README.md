# Diff fixtures

Every `.diff` here is the literal byte output of `git diff` run against a
scratch repository under `/tmp`. The scratch repos were committed with a
fake-local git identity and never pushed, and the Python in them is throwaway
and obviously not real code. Nothing here was transcribed by hand: if a fixture
did not come out of git, it does not belong in this directory.

The generator that builds them lives outside the repo (the scratch tree is not
part of the package), but each fixture below names the exact `git` shape it
exists to exercise.

| File | What it proves the parser handles |
|---|---|
| `shape.diff` | docstring touched, import added, public signature widened, a helper removed and moved to a new file, its call sites updated, and a deletion hunk at the very end of a file. |
| `lifecycle.diff` | added file, deleted file, a rename with an edit (`similarity index`, `rename from`/`rename to`), and a mode-only change (`old mode`/`new mode`, no hunks). |
| `crlf.diff` | new side with CRLF line endings and a `\ No newline at end of file` marker. |
| `mixed_lang.diff` | Python and non-Python files in one diff, for the language split. |
| `symbols.diff` | symbol rename, decorator added, decorator dropped, method added to a class. |
| `unparse.diff` | a change that leaves the new file unparseable; the AST stage must report it, not guess. |
| `empty.diff` | a diff touching zero files. |
