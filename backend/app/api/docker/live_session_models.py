"""Models and constants for operator-visible live browser sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ...utils.env import float_env

LiveSessionKind = Literal["browser"]
LiveSessionState = Literal["active", "expired", "closed"]
LiveControlAction = Literal["click", "key", "text", "wheel", "navigate", "resize"]
LiveAuditActor = Literal["internal", "operator"]

_DEFAULT_TARGET_URL = "https://www.amazon.com/photos/all"
_SESSION_TTL_SECONDS = int(float_env("SUMMITFLOW_LIVE_SESSION_TTL_SECONDS", 30 * 60))
_CONTROL_GRANT_TTL_SECONDS = int(float_env("SUMMITFLOW_LIVE_CONTROL_GRANT_TTL_SECONDS", 10 * 60))
_CDP_HTTP_TIMEOUT_SECONDS = float_env("SUMMITFLOW_LIVE_CDP_HTTP_TIMEOUT", 5.0)
_CDP_WS_TIMEOUT_SECONDS = float_env("SUMMITFLOW_LIVE_CDP_WS_TIMEOUT", 8.0)
_SCREENSHOT_QUALITY = 68
_MAX_VIEWPORT_WIDTH = 3840
_MAX_VIEWPORT_HEIGHT = 2160
_MAX_TEXT_INPUT_CHARS = 4096
_MAX_SECURE_TEXT_INPUT_BYTES = 16 * 1024
_EDITABLE_FOCUS_EXPRESSION = """
(() => {
  const blockedInputTypes = new Set([
    'button',
    'checkbox',
    'color',
    'file',
    'hidden',
    'image',
    'radio',
    'range',
    'reset',
    'submit',
  ]);
  function activeElement(root) {
    const active = root && root.activeElement;
    if (active && active.tagName === 'IFRAME') {
      try {
        return activeElement(active.contentDocument) || active;
      } catch {
        return active;
      }
    }
    return active;
  }
  function isEditable(element) {
    if (!element) return false;
    if (element.isContentEditable) return true;
    if (element.disabled || element.readOnly) return false;
    const tagName = element.tagName;
    if (tagName === 'TEXTAREA') return true;
    if (tagName !== 'INPUT') return false;
    const type = (element.getAttribute('type') || 'text').toLowerCase();
    return !blockedInputTypes.has(type);
  }
  return isEditable(activeElement(document));
})()
"""

_KEY_CODES: dict[str, int] = {
    "Backspace": 8,
    "Tab": 9,
    "Enter": 13,
    "Escape": 27,
    "ArrowLeft": 37,
    "ArrowUp": 38,
    "ArrowRight": 39,
    "ArrowDown": 40,
    "Delete": 46,
    "Home": 36,
    "End": 35,
    "PageUp": 33,
    "PageDown": 34,
}

_KEY_EVENT_CODES: dict[str, str] = {
    "Backspace": "Backspace",
    "Tab": "Tab",
    "Enter": "Enter",
    "Escape": "Escape",
    "ArrowLeft": "ArrowLeft",
    "ArrowUp": "ArrowUp",
    "ArrowRight": "ArrowRight",
    "ArrowDown": "ArrowDown",
    "Delete": "Delete",
    "Home": "Home",
    "End": "End",
    "PageUp": "PageUp",
    "PageDown": "PageDown",
}


class LiveSessionAuditEvent(BaseModel):
    """Sanitized session audit event."""

    at: datetime
    actor: LiveAuditActor
    action: str
    detail: str | None = None


class LiveSessionCreate(BaseModel):
    """Request to create an operator-visible live session."""

    kind: LiveSessionKind = "browser"
    target_url: str = _DEFAULT_TARGET_URL
    viewport_width: int = Field(default=1440, ge=640, le=_MAX_VIEWPORT_WIDTH)
    viewport_height: int = Field(default=900, ge=360, le=_MAX_VIEWPORT_HEIGHT)


class LiveSessionStatus(BaseModel):
    """Public status for a live co-driving session."""

    id: str
    kind: LiveSessionKind
    state: LiveSessionState
    target_url: str
    current_url: str | None = None
    title: str | None = None
    sensitive: bool
    created_at: datetime
    expires_at: datetime
    viewport_width: int
    viewport_height: int
    control_enabled: bool
    control_owner: str | None = None
    control_expires_at: datetime | None = None
    viewer_connected: bool
    token_required: bool
    last_viewed_at: datetime | None = None
    last_controlled_at: datetime | None = None
    audit_events: list[LiveSessionAuditEvent]
    control_policy: str
    capture_policy: str
    browser_target_host: str | None = None
    browser_target_port: int | None = None
    browser_target_source: str | None = None
    browser_target_debug_local: bool = False


class LiveSessionCreated(LiveSessionStatus):
    """Create response with the one-time operator token."""

    operator_token: str


class LiveSessionFrame(BaseModel):
    """Screenshot frame for a live session."""

    session_id: str
    captured_at: datetime
    image_data_url: str
    viewport_width: int
    viewport_height: int
    sensitive: bool


class LiveSessionControl(BaseModel):
    """Remote control command for a live session."""

    action: LiveControlAction
    x: int | None = Field(default=None, ge=0, le=_MAX_VIEWPORT_WIDTH)
    y: int | None = Field(default=None, ge=0, le=_MAX_VIEWPORT_HEIGHT)
    key: str | None = Field(default=None, max_length=32)
    text: str | None = None
    delta_x: int | None = Field(default=0, ge=-4000, le=4000)
    delta_y: int | None = Field(default=0, ge=-4000, le=4000)
    target_url: str | None = Field(default=None, max_length=2048)
    viewport_width: int | None = Field(default=None, ge=640, le=_MAX_VIEWPORT_WIDTH)
    viewport_height: int | None = Field(default=None, ge=360, le=_MAX_VIEWPORT_HEIGHT)


class LiveSessionSensitiveUpdate(BaseModel):
    """Toggle sensitive handling for auth flows."""

    sensitive: bool


class LiveSessionControlGrantUpdate(BaseModel):
    """Toggle operator input control."""

    enabled: bool


@dataclass(slots=True)
class _ManagedLiveSession:
    id: str
    kind: LiveSessionKind
    target_url: str
    target_id: str
    ws_url: str
    operator_token_hash: str
    created_at: datetime
    expires_at: datetime
    viewport_width: int
    viewport_height: int
    sensitive: bool = True
    control_enabled: bool = False
    viewer_connected: bool = False
    last_viewed_at: datetime | None = None
    last_controlled_at: datetime | None = None
    control_expires_at: datetime | None = None
    audit_events: list[LiveSessionAuditEvent] | None = None
    state: LiveSessionState = "active"
    current_url: str | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserTargetStatus:
    host: str | None = None
    port: int | None = None
    source: str | None = None
    debug_local: bool = False
