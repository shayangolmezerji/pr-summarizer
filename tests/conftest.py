"""Shared pytest fixtures: the on-disk diff corpus used across the suite.

Fixtures are real `git diff` output generated against scratch repositories
(see the commit that adds tests/fixtures/), not strings written by hand, so
the parser is tested against the exact bytes git emits.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    if not FIXTURES.is_dir():
        pytest.skip(f"{FIXTURES} not generated yet")
    return FIXTURES
