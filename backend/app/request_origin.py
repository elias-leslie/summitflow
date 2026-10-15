"""Refuse writes that other sites' pages send through the owner's browser.

Loopback callers count as the owner and the Cloudflare Access cookie rides along on
cross-site form posts, so a page the owner happens to open could otherwise POST to the
API (restart services, power off guests, change projects). Browser writes must come from
our own origin; clients that send neither Origin nor Sec-Fetch-Site (st, agents, services)
are unaffected. The pgweb workbench passthrough runs SQL on plain GETs (?query=), so
there even reads must not come from another site's page.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse, Response

from .api.backups.key_endpoints import _require_same_origin

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_OTHER_SITE_FETCH = frozenset({"cross-site", "same-site"})
_WORKBENCH_PASSTHROUGH = re.compile(r"^/api/projects/[^/]+/db-workbench/(?:proxy|static|api|proxyapi)(?:/|$)")


def cross_site_refusal(request: Request) -> Response | None:
    """Return a 403 for a browser write (or workbench call) from another origin, else None."""
    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if request.method not in _UNSAFE_METHODS:
        if not _WORKBENCH_PASSTHROUGH.match(request.url.path):
            return None
        # Typed URLs and bookmarks (Sec-Fetch-Site none) are the owner's own navigation.
        if fetch_site == "none":
            return None
    if fetch_site in _OTHER_SITE_FETCH:
        return JSONResponse({"detail": "Same-origin request required"}, status_code=403)
    if not fetch_site and "origin" not in request.headers:
        return None
    try:
        _require_same_origin(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return None


async def request_origin_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Refuse cross-site writes before identity is resolved."""
    return cross_site_refusal(request) or await call_next(request)
