"""In-memory runtime metrics for the chat and model endpoints."""

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Deque, Dict, Optional


class Metrics:
    """Thread-safe metrics collector for one application process."""

    def __init__(self, recent_limit: int = 50) -> None:
        self._lock = Lock()
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=recent_limit)
        self._requests = {"total": 0, "successful": 0, "failed": 0}
        self._calls = {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "by_route": {
                "small": {"total": 0, "successful": 0, "failed": 0},
                "large": {"total": 0, "successful": 0, "failed": 0},
            },
        }
        self._durations: list[float] = []
        self._started_at = datetime.now(timezone.utc)

    @staticmethod
    def _percentage(value: int, total: int) -> float:
        return round((value / total) * 100, 2) if total else 0.0

    def record_request(self, successful: bool) -> None:
        with self._lock:
            self._requests["total"] += 1
            self._requests["successful" if successful else "failed"] += 1

    def record_call(
        self,
        route: str,
        model: str,
        successful: bool,
        duration_ms: float,
        error: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        status = "success" if successful else "failed"
        with self._lock:
            self._calls["total"] += 1
            self._calls[status == "success" and "successful" or "failed"] += 1
            route_stats = self._calls["by_route"][route]
            route_stats["total"] += 1
            route_stats[status == "success" and "successful" or "failed"] += 1
            self._durations.append(duration_ms)
            self._recent.appendleft(
                {
                    "timestamp": now,
                    "route": route,
                    "model": model,
                    "status": status,
                    "duration_ms": round(duration_ms, 2),
                    "error": error,
                }
            )

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            durations = list(self._durations)
            calls = {
                "total": self._calls["total"],
                "successful": self._calls["successful"],
                "failed": self._calls["failed"],
                "success_percentage": self._percentage(
                    self._calls["successful"], self._calls["total"]
                ),
                "failure_percentage": self._percentage(
                    self._calls["failed"], self._calls["total"]
                ),
                "by_route": {
                    route: dict(stats)
                    for route, stats in self._calls["by_route"].items()
                },
            }
            timing = {
                "average_ms": round(sum(durations) / len(durations), 2)
                if durations
                else 0.0,
                "minimum_ms": round(min(durations), 2) if durations else 0.0,
                "maximum_ms": round(max(durations), 2) if durations else 0.0,
                "p95_ms": round(
                    sorted(durations)[max(0, (len(durations) * 95 + 99) // 100 - 1)],
                    2,
                )
                if durations
                else 0.0,
            }
            requests = dict(self._requests)
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "started_at": self._started_at.isoformat(),
                "requests": {
                    **requests,
                    "success_percentage": self._percentage(
                        requests["successful"], requests["total"]
                    ),
                    "failure_percentage": self._percentage(
                        requests["failed"], requests["total"]
                    ),
                },
                "calls": calls,
                "timing_ms": timing,
                "recent_calls": list(self._recent),
            }


metrics = Metrics()
