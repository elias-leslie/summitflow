"""CLI test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from cli.commands import compactness


@pytest.fixture(autouse=True)
def _pin_compactness_policy_defaults() -> Iterator[None]:
    """Pin the compactness policy to dataclass defaults for unit tests.

    Without this, `_get_policy()` hits the live Agent Hub backend and tests
    that assert against the documented default thresholds (280 chars, 4 lines)
    fail when the DB policy diverges.
    """
    compactness._policy_cache = compactness._DEFAULT_POLICY
    yield
    compactness._policy_cache = None
