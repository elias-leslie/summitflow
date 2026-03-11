from __future__ import annotations

import pytest


def test_dispatch_callback_raises_on_unknown_stage() -> None:
    from app.workflows.pipeline import _make_dispatch_callback

    dispatch = _make_dispatch_callback()

    with pytest.raises(ValueError, match="Unknown workflow stage: missing-stage"):
        dispatch("missing-stage", "task-123", "project-123")
