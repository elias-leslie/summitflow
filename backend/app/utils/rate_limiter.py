"""Redis-based rate limiter for extraction throttling.

Uses a sliding window algorithm to track requests per minute.
"""

from __future__ import annotations

import time
from typing import NamedTuple

import redis

from ..logging_config import get_logger

logger = get_logger(__name__)

# Redis connection (same as used by observation processor)
REDIS_URL = "redis://localhost:6379/1"

# Key prefix for rate limiting
RATE_LIMIT_PREFIX = "extraction_rate:"


class RateLimitResult(NamedTuple):
    """Result of a rate limit check."""

    allowed: bool
    current_count: int
    limit: int
    remaining: int
    reset_in_seconds: int


def check_extraction_rate(project_id: str, rpm_limit: int) -> RateLimitResult:
    """Check if an extraction request is allowed under the rate limit.

    Uses a sliding window counter with 1-minute windows.

    Args:
        project_id: Project ID
        rpm_limit: Requests per minute limit (60 = unlimited)

    Returns:
        RateLimitResult with allowed status and metrics
    """
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
        r = redis.from_url(REDIS_URL)
        key = f"{RATE_LIMIT_PREFIX}{project_id}"
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
                "extraction_rate_limited",
                project_id=project_id,
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
            "extraction_rate_allowed",
            project_id=project_id,
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


def get_extraction_metrics(project_id: str) -> dict[str, int]:
    """Get current extraction rate metrics for a project.

    Args:
        project_id: Project ID

    Returns:
        Dict with current_minute_count and requests_today
    """
    try:
        r = redis.from_url(REDIS_URL)
        key = f"{RATE_LIMIT_PREFIX}{project_id}"
        now = time.time()
        window_start = now - 60

        # Remove expired and count current
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        results = pipe.execute()

        # Also get daily counter
        daily_key = f"{RATE_LIMIT_PREFIX}daily:{project_id}"
        daily_count = r.get(daily_key)

        return {
            "current_minute_count": results[1],
            "requests_today": int(daily_count) if daily_count else 0,
        }

    except redis.RedisError:
        return {"current_minute_count": 0, "requests_today": 0}


def increment_daily_counter(project_id: str) -> None:
    """Increment the daily extraction counter for metrics.

    Resets at midnight UTC.

    Args:
        project_id: Project ID
    """
    try:
        r = redis.from_url(REDIS_URL)
        daily_key = f"{RATE_LIMIT_PREFIX}daily:{project_id}"

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
