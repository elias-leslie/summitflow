"""The coordination store: Tether's coordination documents (aico-hook and `aico` read and write the same ones).

One JSON document per project (leases, writer sets) plus ``_coord`` (identity registry, handshake messages, peer
notes) live in Tether (tether.db ``coord_docs``, ``/v1/coordination/docs``). Aico owns them; this module is the
narrow seam the remaining SummitFlow code (leases.py, coord_lineage.py, coord.py) reads and writes through, in
place of the old ``~/.summitflow/leases`` files and their flock. A writer locks the document, reads, writes with
the lock's token, then releases.

When Tether does not answer, leases are advisory: a read gives an empty document and a write is dropped, after
one warning on stderr. ``ST_LEASES_DIR`` (tests, or pointing the old files back) selects the file store instead.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

_TIMEOUT = 3.0
_LOCK_WAIT_MS = 4000
_LOCK_TTL_MS = 8000
_held: dict[str, str] = {}
_warned = False


_has_routes: bool | None = None


def enabled() -> bool:
    """True unless ST_LEASES_DIR selects the old file store, or this host's Tether predates the coordination routes.

    An agent host can run an older Tether (404 on the route): its leases stay in files there. A Tether that
    does not answer at all is not a reason to switch store; it counts as enabled and the calls degrade.
    """
    global _has_routes
    if os.environ.get("ST_LEASES_DIR"):
        return False
    if _has_routes is None:
        answer = _request("GET", "/v1/coordination/docs")
        _has_routes = not (answer is not None and answer[0] == 404)
    return _has_routes


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any] | None:
    global _warned
    try:
        from app.services import tether

        return tether.request(method, path, body, timeout=_TIMEOUT)
    except Exception as exc:  # no socket, a refused connection, a bad answer: advisory leases go on without it
        if not _warned:
            _warned = True
            print(f"WARNING coordination store (Tether) did not answer ({type(exc).__name__}); "
                  "leases and requests are unknown this call", file=sys.stderr)
        return None


def _path(name: str) -> str:
    return f"/v1/coordination/docs/{quote(name, safe='')}"


def read(name: str) -> dict[str, Any]:
    answer = _request("GET", _path(name))
    if answer is None or answer[0] != 200 or not isinstance(answer[1], dict):
        return {}
    doc = answer[1].get("doc")
    return doc if isinstance(doc, dict) else {}


def write(name: str, doc: dict[str, Any]) -> None:
    """Replace the document; the caller holds its lock."""
    token = _held.get(name)
    if token is None:
        return  # no lock was taken (Tether did not answer): nothing is stored
    _request("PUT", _path(name), {"doc": doc, "lock": token})


def names() -> list[str]:
    answer = _request("GET", "/v1/coordination/docs")
    if answer is None or answer[0] != 200 or not isinstance(answer[1], dict):
        return []
    return sorted(str(item["name"]) for item in answer[1].get("items") or [] if isinstance(item, dict) and "name" in item)


@contextmanager
def lock(name: str) -> Iterator[None]:
    answer = _request("POST", _path(name) + "/lock", {"waitMs": _LOCK_WAIT_MS, "ttlMs": _LOCK_TTL_MS})
    token = answer[1].get("lock") if answer and answer[0] == 200 and isinstance(answer[1], dict) else None
    if token:
        _held[name] = str(token)
    try:
        yield
    finally:
        if token:
            _held.pop(name, None)
            _request("DELETE", _path(name) + f"/lock?lock={quote(str(token), safe='')}")
