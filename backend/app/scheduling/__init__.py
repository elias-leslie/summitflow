"""Scheduling module for event-driven task dispatch.

Provides:
- TaskSchedule: Discriminated union type for at/every/cron schedules
- EventDispatcher: Redis pub/sub for immediate task dispatch
"""

from .dispatch import EventDispatcher, get_dispatcher
from .types import CronSchedule, EverySchedule, OnceSchedule, TaskSchedule

__all__ = [
    "CronSchedule",
    "EventDispatcher",
    "EverySchedule",
    "OnceSchedule",
    "TaskSchedule",
    "get_dispatcher",
]
