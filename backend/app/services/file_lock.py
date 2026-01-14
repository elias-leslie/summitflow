"""File Locking for Concurrent Operations.

Thread-safe and process-safe file locking utilities for git operations.
Uses fcntl.flock() on Unix systems for proper cross-process locking.

Based on Auto-Claude reference implementation.

Example Usage:
    # Simple file locking
    with FileLock("/path/to/repo/.git", timeout=5.0):
        # Do work with locked resource
        pass
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class FileLockError(Exception):
    """Raised when file locking operations fail."""

    pass


class FileLockTimeout(FileLockError):
    """Raised when lock acquisition times out."""

    pass


def _try_lock(fd: int, exclusive: bool = True) -> None:
    """Try to acquire a file lock (non-blocking).

    Args:
        fd: File descriptor
        exclusive: Whether to use exclusive lock (default True)

    Raises:
        FileLockError: If fcntl is not available
        BlockingIOError: If lock is held by another process
    """
    if fcntl is None:
        raise FileLockError("fcntl is required for file locking on non-Windows platforms")

    lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fcntl.flock(fd, lock_mode | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    """Release a file lock.

    Args:
        fd: File descriptor
    """
    if fcntl is None:
        return
    fcntl.flock(fd, fcntl.LOCK_UN)


class FileLock:
    """Cross-process file lock using fcntl.flock.

    Supports context manager for safe acquisition and release.

    Args:
        filepath: Path to file/directory to lock (creates .lock file)
        timeout: Maximum seconds to wait for lock (default: 10.0)
        exclusive: Whether to use exclusive lock (default: True)

    Example:
        with FileLock("/path/to/repo"):
            # Repository is locked
            subprocess.run(["git", "worktree", "add", ...])
    """

    def __init__(
        self,
        filepath: str | Path,
        timeout: float = 10.0,
        exclusive: bool = True,
    ):
        self.filepath = Path(filepath)
        self.timeout = timeout
        self.exclusive = exclusive
        self._lock_file: Path | None = None
        self._fd: int | None = None

    def _get_lock_file(self) -> Path:
        """Get lock file path (separate .lock file)."""
        return self.filepath.parent / f"{self.filepath.name}.lock"

    def _acquire_lock(self) -> None:
        """Acquire the file lock (blocking with timeout)."""
        self._lock_file = self._get_lock_file()
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Open/create lock file
        self._fd = os.open(str(self._lock_file), os.O_CREAT | os.O_RDWR)

        # Try to acquire lock with timeout
        start_time = time.time()
        retry_delay = 0.01  # Start with 10ms

        while True:
            try:
                _try_lock(self._fd, self.exclusive)
                logger.debug(f"Lock acquired: {self._lock_file}")
                return
            except (BlockingIOError, OSError) as e:
                elapsed = time.time() - start_time
                if elapsed >= self.timeout:
                    os.close(self._fd)
                    self._fd = None
                    raise FileLockTimeout(
                        f"Failed to acquire lock on {self.filepath} within {self.timeout}s"
                    ) from e

                # Exponential backoff with cap
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 0.5)

    def _release_lock(self) -> None:
        """Release the file lock."""
        if self._fd is not None:
            try:
                _unlock(self._fd)
                os.close(self._fd)
                logger.debug(f"Lock released: {self._lock_file}")
            except Exception:
                pass  # Best effort cleanup
            finally:
                self._fd = None

        # Clean up lock file
        if self._lock_file and self._lock_file.exists():
            with suppress(Exception):
                self._lock_file.unlink()

    def __enter__(self) -> FileLock:
        """Context manager entry."""
        self._acquire_lock()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object
    ) -> None:
        """Context manager exit."""
        self._release_lock()


@contextmanager
def repo_lock(repo_path: str | Path, timeout: float = 10.0) -> Generator[FileLock, None, None]:
    """Context manager for locking a git repository.

    Creates a lock file adjacent to the .git directory.

    Args:
        repo_path: Path to repository root
        timeout: Lock timeout in seconds

    Example:
        with repo_lock("/path/to/repo"):
            # Safe to do git worktree operations
            pass
    """
    repo_path = Path(repo_path)
    git_dir = repo_path / ".git"

    if not git_dir.exists():
        raise FileLockError(f"Not a git repository: {repo_path}")

    lock = FileLock(git_dir, timeout=timeout, exclusive=True)
    lock._acquire_lock()
    try:
        yield lock
    finally:
        lock._release_lock()
