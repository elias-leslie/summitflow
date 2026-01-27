"""Redis-based rate limiter for extraction throttling.

Uses a sliding window algorithm to track requests per minute.
Global extraction settings are stored in Redis for simplicity.
"""

from __future__ import annotations

import json
import time
from typing import NamedTuple, TypedDict

import redis

from ..logging_config import get_logger

logger = get_logger(__name__)

# Redis connection (same as used by observation processor)
REDIS_URL = "redis://localhost:6379/1"

# Key prefix for rate limiting
RATE_LIMIT_PREFIX = "extraction_rate:"

# Key for global extraction settings
GLOBAL_EXTRACTION_KEY = "extraction_settings:global"

# Default global settings
DEFAULT_GLOBAL_RPM = 10


class GlobalExtractionSettings(TypedDict):
    """Global extraction throttle settings."""

    enabled: bool
    rpm_limit: int


def get_global_extraction_settings() -> GlobalExtractionSettings:
    """Get global extraction settings from Redis.

    Returns:
        GlobalExtractionSettings with enabled and rpm_limit
    """
    try:
        r = redis.from_url(REDIS_URL)  # type: ignore[no-untyped-call]
        data = r.get(GLOBAL_EXTRACTION_KEY)
        if data:
            settings = json.loads(data)
            return {
                "enabled": settings.get("enabled", True),
                "rpm_limit": settings.get("rpm_limit", DEFAULT_GLOBAL_RPM),
            }
    except (redis.RedisError, json.JSONDecodeError) as e:
        logger.warning("get_global_extraction_settings_failed", error=str(e))

    return {"enabled": True, "rpm_limit": DEFAULT_GLOBAL_RPM}


def set_global_extraction_settings(
    enabled: bool | None = None, rpm_limit: int | None = None
) -> GlobalExtractionSettings:
    """Update global extraction settings in Redis.

    Args:
        enabled: Whether extraction is enabled (optional)
        rpm_limit: Requests per minute limit (optional)

    Returns:
        Updated GlobalExtractionSettings
    """
    current = get_global_extraction_settings()

    if enabled is not None:
        current["enabled"] = enabled
    if rpm_limit is not None:
        current["rpm_limit"] = rpm_limit

    try:
        r = redis.from_url(REDIS_URL)  # type: ignore[no-untyped-call]
        r.set(GLOBAL_EXTRACTION_KEY, json.dumps(current))
        logger.info(
            "global_extraction_settings_updated",
            enabled=current["enabled"],
            rpm_limit=current["rpm_limit"],
        )
    except redis.RedisError as e:
        logger.error("set_global_extraction_settings_failed", error=str(e))

    return current


def get_global_rpm_limit() -> int:
    """Get the global RPM limit.

    Returns:
        RPM limit (0 if disabled)
    """
    settings = get_global_extraction_settings()
    if not settings["enabled"]:
        return 0
    return settings["rpm_limit"]


class RateLimitResult(NamedTuple):
    """Result of a rate limit check."""

    allowed: bool
    current_count: int
    limit: int
    remaining: int
    reset_in_seconds: int


def check_extraction_rate() -> RateLimitResult:
    """Check if an extraction request is allowed under the global rate limit.

    Uses a sliding window counter with 1-minute windows.
    Checks the global extraction settings (not per-project).

    Returns:
        RateLimitResult with allowed status and metrics
    """
    rpm_limit = get_global_rpm_limit()

    # 60 RPM = unlimited
    if rpm_limit >= 60:
        return RateLimitResult(
            allowed=True,
            current_count=0,
            limit=rpm_limit,
            remaining=rpm_limit,
            reset_in_seconds=0,
        )

    # 0 RPM = disabled
    if rpm_limit <= 0:
        return RateLimitResult(
            allowed=False,
            current_count=0,
            limit=0,
            remaining=0,
            reset_in_seconds=60,
        )

    try:
        r = redis.from_url(REDIS_URL)  # type: ignore[no-untyped-call]
        # Global key - not per-project
        key = f"{RATE_LIMIT_PREFIX}global"
        now = time.time()
        window_start = now - 60  # 1-minute sliding window

        # Use a pipeline for atomic operations
        pipe = r.pipeline()

        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)

        # Count current entries
        pipe.zcard(key)

        # Execute
        results = pipe.execute()
        current_count = results[1]

        if current_count >= rpm_limit:
            # Over limit - calculate reset time
            oldest = r.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_time = oldest[0][1]
                reset_in = max(1, int(60 - (now - oldest_time)))
            else:
                reset_in = 60

            logger.info(
                "extraction_rate_limited_global",
                current=current_count,
                limit=rpm_limit,
                reset_in=reset_in,
            )

            return RateLimitResult(
                allowed=False,
                current_count=current_count,
                limit=rpm_limit,
                remaining=0,
                reset_in_seconds=reset_in,
            )

        # Under limit - add this request
        pipe = r.pipeline()
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, 120)  # Expire key after 2 minutes
        pipe.execute()

        remaining = max(0, rpm_limit - current_count - 1)

        logger.debug(
            "extraction_rate_allowed_global",
            current=current_count + 1,
            limit=rpm_limit,
            remaining=remaining,
        )

        return RateLimitResult(
            allowed=True,
            current_count=current_count + 1,
            limit=rpm_limit,
            remaining=remaining,
            reset_in_seconds=0,
        )

    except redis.RedisError as e:
        # Redis down - allow request but log warning
        logger.warning("rate_limiter_redis_error", error=str(e))
        return RateLimitResult(
            allowed=True,
            current_count=0,
            limit=rpm_limit,
            remaining=rpm_limit,
            reset_in_seconds=0,
        )


def get_extraction_metrics() -> dict[str, int]:
    """Get current global extraction rate metrics.

    Returns:
        Dict with current_minute_count and requests_today
    """
    try:
        r = redis.from_url(REDIS_URL)  # type: ignore[no-untyped-call]
        key = f"{RATE_LIMIT_PREFIX}global"
        now = time.time()
        window_start = now - 60

        # Remove expired and count current
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        results = pipe.execute()

        # Also get daily counter
        daily_key = f"{RATE_LIMIT_PREFIX}daily:global"
        daily_count = r.get(daily_key)

        return {
            "current_minute_count": results[1],
            "requests_today": int(daily_count) if daily_count else 0,
        }

    except redis.RedisError:
        return {"current_minute_count": 0, "requests_today": 0}


def increment_daily_counter() -> None:
    """Increment the global daily extraction counter for metrics.

    Resets at midnight UTC.
    """
    try:
        r = redis.from_url(REDIS_URL)  # type: ignore[no-untyped-call]
        daily_key = f"{RATE_LIMIT_PREFIX}daily:global"

        # Increment and set expiry to end of day
        pipe = r.pipeline()
        pipe.incr(daily_key)
        # Calculate seconds until midnight UTC
        import datetime

        now = datetime.datetime.now(tz=datetime.UTC)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow += datetime.timedelta(days=1)
        seconds_until_midnight = int((tomorrow - now).total_seconds())
        pipe.expire(daily_key, seconds_until_midnight)
        pipe.execute()

    except redis.RedisError as e:
        logger.warning("daily_counter_increment_failed", error=str(e))


# --- Cleanup Aggressiveness Settings ---

CLEANUP_SETTINGS_KEY = "cleanup_settings:global"


class CleanupPreset(TypedDict):
    """Cleanup preset definition."""

    label: str
    min_age_days: int
    min_relevance: float


# Cleanup presets: level -> preset config
CLEANUP_PRESETS: dict[int, CleanupPreset] = {
    0: {"label": "Manual Only", "min_age_days": 999, "min_relevance": 0.0},
    1: {"label": "Conservative", "min_age_days": 30, "min_relevance": 0.3},
    2: {"label": "Moderate", "min_age_days": 14, "min_relevance": 0.4},
    3: {"label": "Aggressive", "min_age_days": 7, "min_relevance": 0.5},
}

DEFAULT_CLEANUP_LEVEL = 3  # Aggressive by default per user request


class CleanupSettings(TypedDict):
    """Global cleanup aggressiveness settings."""

    level: int  # 0-3: manual, conservative, moderate, aggressive
    min_age_days: int  # Patterns younger than this are never cleaned
    min_relevance: float  # Patterns with relevance below this get cleaned


def get_cleanup_settings() -> CleanupSettings:
    """Get global cleanup settings from Redis.

    Returns:
        CleanupSettings with level and derived thresholds
    """
    try:
        r = redis.from_url(REDIS_URL)  # type: ignore[no-untyped-call]
        data = r.get(CLEANUP_SETTINGS_KEY)
        if data:
            settings = json.loads(data)
            level = settings.get("level", DEFAULT_CLEANUP_LEVEL)
            preset = CLEANUP_PRESETS.get(level, CLEANUP_PRESETS[DEFAULT_CLEANUP_LEVEL])
            return {
                "level": level,
                "min_age_days": preset["min_age_days"],
                "min_relevance": preset["min_relevance"],
            }
    except (redis.RedisError, json.JSONDecodeError) as e:
        logger.warning("get_cleanup_settings_failed", error=str(e))

    # Default to aggressive
    preset = CLEANUP_PRESETS[DEFAULT_CLEANUP_LEVEL]
    return {
        "level": DEFAULT_CLEANUP_LEVEL,
        "min_age_days": preset["min_age_days"],
        "min_relevance": preset["min_relevance"],
    }


def set_cleanup_settings(level: int) -> CleanupSettings:
    """Update global cleanup settings in Redis.

    Args:
        level: Cleanup aggressiveness level (0-3)

    Returns:
        Updated CleanupSettings
    """
    # Clamp level to valid range
    level = max(0, min(3, level))
    preset = CLEANUP_PRESETS[level]

    settings: CleanupSettings = {
        "level": level,
        "min_age_days": preset["min_age_days"],
        "min_relevance": preset["min_relevance"],
    }

    try:
        r = redis.from_url(REDIS_URL)  # type: ignore[no-untyped-call]
        r.set(CLEANUP_SETTINGS_KEY, json.dumps(settings))
        logger.info(
            "cleanup_settings_updated",
            cleanup_level=level,
            label=preset["label"],
            min_age_days=preset["min_age_days"],
            min_relevance=preset["min_relevance"],
        )
    except redis.RedisError as e:
        logger.error("set_cleanup_settings_failed", error=str(e))

    return settings
