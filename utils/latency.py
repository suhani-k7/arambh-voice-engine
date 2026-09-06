"""Lightweight per-call latency instrumentation.

Call sites use `mark`/`elapsed_since_ms` to measure the gap between two
events (e.g. STT finalization -> TTS synthesis start), and `timed_stage`
to measure the duration of a single async call (e.g. an LLM round trip).
All measurements are logged via the app logger and kept in memory so
they can be read back per call_sid (see main.py's /dev/last-call-metrics).
"""
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator

from utils.logger import AppLogger

logger = AppLogger.get_instance()

_marks: dict[tuple[str, str], float] = {}
_call_metrics: dict[str, list[dict]] = defaultdict(list)


def mark(call_sid: str, event: str) -> None:
    """Record a point-in-time marker for `event` on this call_sid."""
    _marks[(call_sid, event)] = time.perf_counter()


def elapsed_since_ms(call_sid: str, event: str) -> float | None:
    """Milliseconds since `mark(call_sid, event)` was last called, or None if never marked."""
    start = _marks.get((call_sid, event))
    return (time.perf_counter() - start) * 1000 if start is not None else None


def record_duration(call_sid: str, stage: str, duration_ms: float) -> None:
    """Log a stage's duration and store it for later retrieval via get_call_metrics."""
    logger.info("Latency | call_sid=%s | stage=%s | duration_ms=%.1f", call_sid, stage, duration_ms)
    _call_metrics[call_sid].append({
        "stage": stage,
        "duration_ms": round(duration_ms, 1),
        "recorded_at": time.time(),
    })


@asynccontextmanager
async def timed_stage(call_sid: str, stage: str) -> AsyncIterator[None]:
    """Time an async block and record its duration under `stage` for call_sid."""
    start = time.perf_counter()
    try:
        yield
    finally:
        record_duration(call_sid, stage, (time.perf_counter() - start) * 1000)


def get_call_metrics(call_sid: str) -> list[dict]:
    """Return all recorded stage timings for a call_sid, in the order they were recorded."""
    return list(_call_metrics.get(call_sid, []))
