"""Lazy compatibility bridge to the public browser owner package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .browser_support import (
    browser_page_target_ids as browser_page_target_ids,
)
from .browser_support import (
    close_browser_targets as close_browser_targets,
)


def run_browser_check(args: list[str], **kwargs: Any) -> int:
    """Invoke the installed owner implementation only when called."""
    owner_run_browser_check = import_module("browser_automation.check").run_browser_check
    return owner_run_browser_check(args, **kwargs)
