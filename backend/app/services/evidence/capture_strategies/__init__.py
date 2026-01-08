"""Evidence capture strategies for different entry types."""

from .base import CaptureConfig, CaptureStrategy, EvidenceResult, EvidenceType, ExplorerEntry
from .browser import BrowserCapture
from .http import HttpCapture, capture_api_endpoint
from .shell import ShellCapture, capture_shell_command
from .sql import SqlCapture, capture_table_schema
from .test_runner import TestRunnerCapture, run_tests

__all__ = [
    "BrowserCapture",
    "CaptureConfig",
    "CaptureStrategy",
    "EvidenceResult",
    "EvidenceType",
    "ExplorerEntry",
    "HttpCapture",
    "ShellCapture",
    "SqlCapture",
    "TestRunnerCapture",
    "capture_api_endpoint",
    "capture_shell_command",
    "capture_table_schema",
    "run_tests",
]
