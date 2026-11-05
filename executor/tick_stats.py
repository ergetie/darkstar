"""
Tick statistics

Unthrottled executor tick counters, kept in hourly UTC buckets and persisted as
JSON in the ``system_state`` key/value table (key ``executor_tick_stats``). The
``command_success`` invariant reads them; ``execution_log`` is throttled (one
row per change or heartbeat) and cannot give a true success rate.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

logger = logging.getLogger(__name__)

TICK_STATS_KEY = "executor_tick_stats"
TICK_STATS_VERSION = 1
RETENTION_HOURS = 25
MAX_ACTIONS_PER_BUCKET = 20
MAX_ERROR_CHARS = 200

# (action_type, entity_id, error text) of one failed action in a tick
TickFailure = tuple[str, str | None, str]


def bucket_key(moment: datetime) -> str:
    """Hourly UTC bucket key, ``YYYY-MM-DDTHH`` (UTC avoids DST ambiguity)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H")


def bucket_start(key: str) -> datetime:
    """Start instant (UTC) of a bucket key."""
    return datetime.strptime(key, "%Y-%m-%dT%H").replace(tzinfo=UTC)


class TickStats:
    """In-memory hourly tick buckets with JSON persistence."""

    def __init__(self) -> None:
        # {bucket_key: {"t": total, "f": failed, "a": {action: {"n", "entity", "err"}}}}
        self.buckets: dict[str, dict[str, Any]] = {}
        self.dirty = False

    def record(self, now: datetime, failures: list[TickFailure]) -> None:
        """Count one executed tick; ``failures`` non-empty marks it failed (once)."""
        bucket = self.buckets.setdefault(bucket_key(now), {"t": 0, "f": 0, "a": {}})
        bucket["t"] += 1
        if failures:
            bucket["f"] += 1
            actions: dict[str, dict[str, Any]] = bucket["a"]
            for action_type, entity_id, error in failures:
                entry = actions.get(action_type)
                if entry is None:
                    if len(actions) >= MAX_ACTIONS_PER_BUCKET:
                        continue
                    entry = actions[action_type] = {"n": 0, "entity": None, "err": ""}
                entry["n"] += 1
                entry["entity"] = entity_id
                entry["err"] = error[:MAX_ERROR_CHARS]
        self.prune(now)
        self.dirty = True

    def prune(self, now: datetime) -> None:
        """Drop buckets older than the retention window."""
        cutoff = now.astimezone(UTC) - timedelta(hours=RETENTION_HOURS)
        stale = [key for key in self.buckets if bucket_start(key) < cutoff]
        for key in stale:
            del self.buckets[key]
        if stale:
            self.dirty = True

    def to_json(self) -> str:
        return json.dumps({"v": TICK_STATS_VERSION, "buckets": self.buckets})

    @classmethod
    def from_json(cls, raw: str | None) -> "TickStats":
        """Restore from JSON; absent, corrupt or foreign-version data yields an empty instance."""
        stats = cls()
        if not raw:
            return stats
        try:
            data: Any = json.loads(raw)
            if not isinstance(data, dict):
                return stats
            payload = cast("dict[str, Any]", data)
            raw_buckets: Any = payload.get("buckets", {})
            if payload.get("v") != TICK_STATS_VERSION or not isinstance(raw_buckets, dict):
                return stats
            restored: dict[str, dict[str, Any]] = {}
            for key, bucket in cast("dict[str, Any]", raw_buckets).items():
                bucket_start(key)  # validates the key
                restored[key] = {
                    "t": int(bucket["t"]),
                    "f": int(bucket["f"]),
                    "a": dict(bucket.get("a", {})),
                }
            stats.buckets = restored
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("Ignoring unreadable tick stats: %s", e)
            stats.buckets = {}
        return stats
