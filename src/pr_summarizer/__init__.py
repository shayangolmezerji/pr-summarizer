"""Structural summaries of pull-request diffs.

The public surface is the pipeline in docs/spec.md: parse a unified diff, map
each Python file's changed regions onto symbols via ``ast``, render a
deterministic brief, and optionally hand that brief to a model. Nothing here
reads a working tree or the network on import.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
