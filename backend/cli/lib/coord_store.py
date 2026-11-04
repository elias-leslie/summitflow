"""The coordination store: Tether's coordination documents (aico-hook and `aico` read and write the same ones).

One JSON document per project (leases, writer sets) plus ``_coord`` (identity registry, handshake messages, peer
notes) live in Tether (tether.db ``coord_docs``, ``/v1/coordination/docs``). Aico owns them; this module is the
narrow seam the remaining SummitFlow code (leases.py, coord_lineage.py, coord.py) reads and writes through, in
place of the old ``~/.summitflow/leases`` files and their flock.

A change is compare-and-set: ``with lock(name)`` reads the document and its version, ``read`` inside it serves
that copy, and ``write`` saves against that version. When someone else saved first the write raises
``Conflict``; a function decorated with ``@retrying`` then runs again on a fresh read. Nothing is held between
the read and the write, so a caller that dies leaves nothing behind and no update is lost.

A store that does not answer raises ``Unavailable`` (an ``OSError``, "coordination store unavailable"), never
an empty document: nothing is written over a document that could not be read, and the safety checks
(``st commit``'s sweep check, ``coord.guard``, snapshot ownership) refuse. ``ST_LEASES_DIR`` (tests, or pointing
the old files back) selects the file store instead.
"""

from __future__ import annotations

import copy
import functools
import os
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

_TIMEOUT = 3.0
_ATTEMPTS = 40  # reads and writes of one change before giving up
_BACKOFF = 0.004  # the jittered pause after a lost race grows by this per attempt (at most 10x)
# Tether's document limit (packages/tether/src/coordination/docs.ts MAX_DOC_BYTES); an answer carries one document.
MAX_DOC_BYTES = 2 * 1024 * 1024 + 64 * 1024

_has_routes: bool | None = None


class Unavailable(OSError):
    """The coordination store did not answer (or kept changing): its documents are unknown, not empty."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"coordination store unavailable ({detail})")


class Conflict(Unavailable):
    """Someone saved the document since this change read it; ``@retrying`` redoes the change."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} changed since it was read")
        self.name = name


@dataclass
class _Change:
    version: int
    doc: dict[str, Any]


_changes: dict[str, _Change] = {}


def enabled() -> bool:
    """True unless ST_LEASES_DIR selects the old file store, or this host's Tether predates the coordination routes.

    An agent host can run an older Tether (404 on the route): its leases stay in files there. A Tether that
    does not answer at all is not a reason to switch store; it counts as enabled and the calls raise Unavailable.
    """
    global _has_routes
    if os.environ.get("ST_LEASES_DIR"):
        return False
    if _has_routes is None:
        try:
            status, _ = _request("GET", "/v1/coordination/docs")
        except Unavailable:
            return True
        _has_routes = status != 404
    return _has_routes


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    try:
        from app.services import tether

        return tether.request(method, path, body, timeout=_TIMEOUT, max_bytes=MAX_DOC_BYTES)
    except Exception as exc:  # no socket, a refused connection, a timeout, a bad answer
        raise Unavailable(type(exc).__name__) from exc


def _path(name: str) -> str:
    return f"/v1/coordination/docs/{quote(name, safe='')}"


def _fetch(name: str) -> tuple[int, dict[str, Any]]:
    status, body = _request("GET", _path(name))
    doc = body.get("doc") if isinstance(body, dict) else None
    version = body.get("version") if isinstance(body, dict) else None
    if status != 200 or not isinstance(doc, dict) or not isinstance(version, int):
        raise Unavailable(f"reading {name} answered {status}")
    return version, doc


def read(name: str) -> dict[str, Any]:
    """The document as the change in progress read it, else a fresh read; raises Unavailable, never ``{}``."""
    change = _changes.get(name)
    if change is not None:
        return copy.deepcopy(change.doc)
    return _fetch(name)[1]


def write(name: str, doc: dict[str, Any]) -> None:
    """Replace the document inside ``lock(name)``, against the version that change read."""
    change = _changes.get(name)
    if change is None:
        raise RuntimeError(f"write of {name} outside coord_store.lock")
    status, body = _request("PUT", _path(name), {"doc": doc, "version": change.version})
    if status == 409 and isinstance(body, dict) and body.get("error") == "version_conflict":
        raise Conflict(name)
    version = body.get("version") if isinstance(body, dict) else None
    if status != 200 or not isinstance(version, int):
        raise Unavailable(f"writing {name} answered {status}")
    change.version, change.doc = version, copy.deepcopy(doc)


def names() -> list[str]:
    status, body = _request("GET", "/v1/coordination/docs")
    if status != 200 or not isinstance(body, dict):
        raise Unavailable(f"listing documents answered {status}")
    return sorted(str(item["name"]) for item in body.get("items") or [] if isinstance(item, dict) and "name" in item)


@contextmanager
def lock(name: str) -> Iterator[None]:
    """One change of the document (named after the lock it replaces): read now, written against that version.

    Raises Unavailable before the body runs when the document cannot be read. Inside a change of the same
    document it joins that change.
    """
    if name in _changes:
        yield
        return
    version, doc = _fetch(name)
    _changes[name] = _Change(version, doc)
    try:
        yield
    finally:
        _changes.pop(name, None)


def retrying[F: Callable[..., Any]](fn: F) -> F:
    """Run fn again on a fresh read when one of its own changes lost a race (a few times, then Unavailable).

    A conflict on a document a caller further up is changing belongs to that caller and passes through.
    """

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        outer = set(_changes)
        for attempt in range(_ATTEMPTS):
            try:
                return fn(*args, **kwargs)
            except Conflict as exc:
                if exc.name in outer:
                    raise
                if attempt + 1 == _ATTEMPTS:
                    raise Unavailable(f"{exc.name} kept changing under {_ATTEMPTS} tries") from exc
                # Many writers at once: spread the retries so each round has a winner.
                time.sleep(random.uniform(0, min(attempt + 1, 10) * _BACKOFF))
        raise AssertionError("unreachable")

    return run  # type: ignore[return-value]
