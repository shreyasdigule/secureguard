"""
timeout_utils.py — Dynamic Timeout Infrastructure

Purpose
-------
Prevent upstream idle-timeout failures by giving slow SecureGuard computations
(physics digital twin, multi-dimensional risk, causal XAI, telemetry reads) a
generous, configurable, and *self-tuning* time budget instead of a fixed short
one.

Design notes
------------
The original design blocked calls with a watchdog that raised mid-computation.
That is unsafe here: the pipeline mutates shared state (state machine, twin
integration history, SQLite persistence), so aborting a stage part-way through
can corrupt state and produce *more* failures than it prevents.

Instead this module provides:

1. ``operation_timeout``  - a context manager used as a *budget meter*. It
   measures elapsed time, logs a warning when the budget is exceeded, and can be
   made strict (``strict=True``) for call sites where aborting is safe.
2. ``with_pipeline_timeout`` - decorator form of the same budget meter.
3. ``DynamicTimeout`` - an exponential-backoff timeout manager for genuinely
   retryable I/O (e.g. Keycloak JWKS fetches), with jitter to avoid thundering
   herd behaviour.
4. ``adaptive_interval`` - helper that grows UI/poll intervals when the host is
   under load, so slow machines degrade gracefully instead of stalling.

All budgets are environment-overridable so deployments can be tuned without a
code change.
"""

from __future__ import annotations

import functools
import logging
import os
import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

logger = logging.getLogger("secureguard.timeout")

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Environment-tunable budgets (seconds unless suffixed)
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# Base budgets -- deliberately generous so the gateway never sees an idle stream.
BASE_TIMEOUT: float = _env_float("SECUREGUARD_BASE_TIMEOUT", 120.0)          # 2 min
SLOW_TIMEOUT: float = _env_float("SECUREGUARD_SLOW_TIMEOUT", 900.0)         # 15 min
MAX_TIMEOUT: float = _env_float("SECUREGUARD_MAX_TIMEOUT", 3600.0)         # 60 min

# UI / polling intervals (milliseconds unless noted)
TELEMETRY_INTERVAL: float = _env_float("SECUREGUARD_TELEMETRY_INTERVAL", 5.0)   # seconds
CHART_REFRESH_MS: int = _env_int("SECUREGUARD_CHART_REFRESH_MS", 30000)           # 30 s
STREAM_REFRESH_MS: int = _env_int("SECUREGUARD_STREAM_REFRESH_MS", 2000)
HEARTBEAT_MS: int = _env_int("SECUREGUARD_HEARTBEAT_MS", 1000)
CLOCK_MS: int = _env_int("SECUREGUARD_CLOCK_MS", 1000)
FRAME_INTERVAL_MS: int = _env_int("SECUREGUARD_FRAME_INTERVAL_MS", 33)            # ~30 FPS

# Consecutive budget overruns before we escalate to an operator-visible warning.
OVERRUN_WARN_THRESHOLD: int = _env_int("SECUREGUARD_OVERRUN_WARN_THRESHOLD", 3)


class TimeoutError(Exception):  # noqa: A001 - intentionally shadows builtin name
    """Raised when an operation exceeds its allotted budget in strict mode."""


# ---------------------------------------------------------------------------
# Budget metering
# ---------------------------------------------------------------------------

_overrun_counts: Dict[str, int] = {}
_overrun_lock = threading.Lock()


def overrun_count(operation: str) -> int:
    """Number of consecutive budget overruns recorded for ``operation``."""
    with _overrun_lock:
        return _overrun_counts.get(operation, 0)


def reset_overruns(operation: Optional[str] = None) -> None:
    """Clear overrun counters (all operations when ``operation`` is None)."""
    with _overrun_lock:
        if operation is None:
            _overrun_counts.clear()
        else:
            _overrun_counts.pop(operation, None)


def _record_overrun(operation: str, elapsed: float, budget: float) -> None:
    with _overrun_lock:
        _overrun_counts[operation] = _overrun_counts.get(operation, 0) + 1
        count = _overrun_counts[operation]

    logger.warning(
        "operation '%s' exceeded its %.1fs budget (took %.1fs, overrun #%d)",
        operation, budget, elapsed, count,
    )
    if count >= OVERRUN_WARN_THRESHOLD:
        logger.error(
            "operation '%s' has overrun %d consecutive budgets - consider raising "
            "the configured timeout or reducing the workload",
            operation, count,
        )


@contextmanager
def operation_timeout(operation: str, budget: float, strict: bool = False) -> Iterator[None]:
    """
    Context manager that meters ``operation`` against ``budget`` seconds.

    Non-strict (default) mode never interrupts the wrapped block: it only logs
    when the budget is exceeded, which keeps shared pipeline state consistent.
    Strict mode raises :class:`TimeoutError` *after* the block finishes, so the
    caller still observes a clean, non-corrupt state.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - started
        if budget and elapsed > budget:
            _record_overrun(operation, elapsed, budget)
            if strict:
                raise TimeoutError(
                    f"operation '{operation}' exceeded its {budget:.1f}s budget "
                    f"(took {elapsed:.1f}s)"
                )
        elif elapsed <= budget:
            with _overrun_lock:
                _overrun_counts.pop(operation, None)


def with_pipeline_timeout(
    operation: Optional[str] = None,
    budget: Optional[float] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator applying :func:`operation_timeout` to a callable.

    Example
    -------
    >>> @with_pipeline_timeout("risk_assessment", SLOW_TIMEOUT)
    ... def assess(...):
    ...     ...
    """
    resolved_budget = SLOW_TIMEOUT if budget is None else budget

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        name = operation or getattr(func, "__name__", "operation")

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            with operation_timeout(name, resolved_budget):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Retryable I/O with exponential backoff
# ---------------------------------------------------------------------------

class DynamicTimeout:
    """
    Timeout manager for retryable I/O with exponential backoff and jitter.

    Used where an operation genuinely benefits from being *retried* (Keycloak
    JWKS retrieval, telemetry source probing) as opposed to merely *waited on*.
    """

    def __init__(
        self,
        base_timeout: float = BASE_TIMEOUT,
        max_timeout: float = MAX_TIMEOUT,
        backoff_factor: float = 2.0,
        jitter: float = 0.1,
        max_retries: int = 3,
    ) -> None:
        self.base_timeout = base_timeout
        self.max_timeout = max_timeout
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.max_retries = max_retries
        self._consecutive_timeouts = 0
        self._lock = threading.Lock()

    @property
    def consecutive_timeouts(self) -> int:
        with self._lock:
            return self._consecutive_timeouts

    def timeout_for(self, attempt: int = 0) -> float:
        """Timeout for ``attempt``, capped at ``max_timeout`` with jitter."""
        span = min(self.base_timeout * (self.backoff_factor ** attempt), self.max_timeout)
        return max(0.1, span + span * self.jitter * (2.0 * random.random() - 1.0))

    def run(
        self,
        func: Callable[..., T],
        *args: Any,
        timeout_override: Optional[float] = None,
        **kwargs: Any,
    ) -> T:
        """Run ``func`` with per-attempt timeouts; raise TimeoutError on exhaustion."""
        name = getattr(func, "__name__", "operation")
        failure: Optional[BaseException] = None

        for attempt in range(self.max_retries + 1):
            budget = timeout_override or self.timeout_for(attempt)
            outcome: Dict[str, Any] = {}
            done = threading.Event()

            def _worker() -> None:
                try:
                    outcome["value"] = func(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    outcome["error"] = exc
                finally:
                    done.set()

            worker = threading.Thread(target=_worker, name=f"timeout-{name}", daemon=True)
            worker.start()

            if done.wait(timeout=budget):
                if "error" in outcome:
                    raise outcome["error"]
                with self._lock:
                    self._consecutive_timeouts = 0
                return outcome["value"]

            with self._lock:
                self._consecutive_timeouts += 1
            logger.warning(
                "operation '%s' timed out after %.1fs (attempt %d/%d)",
                name, budget, attempt + 1, self.max_retries + 1,
            )
            failure = TimeoutError(f"operation '{name}' timed out after {budget:.1f}s")
            if attempt < self.max_retries:
                time.sleep(min(2.0 * (attempt + 1), 5.0))

        raise failure if failure is not None else TimeoutError(f"operation '{name}' failed")


# Pre-configured managers
fast_timeout = DynamicTimeout(base_timeout=BASE_TIMEOUT, max_timeout=BASE_TIMEOUT * 2, max_retries=1)
slow_timeout = DynamicTimeout(base_timeout=SLOW_TIMEOUT, max_timeout=MAX_TIMEOUT, max_retries=3)


def adaptive_interval(
    base_ms: int,
    load_ratio: float,
    minimum_ms: Optional[int] = None,
    maximum_ms: Optional[int] = None,
) -> int:
    """
    Scale a polling interval by observed system load.

    ``load_ratio`` is typically ``len(running_threads) / max_threads`` or a
    normalised CPU sample in ``0.0..1.0``. Under load the interval grows so the
    event loop is not starved; it never drops below ``minimum_ms`` so the UI
    still feels live.
    """
    floor = base_ms if minimum_ms is None else minimum_ms
    ceiling = base_ms * 4 if maximum_ms is None else maximum_ms
    ratio = max(0.0, min(1.0, float(load_ratio)))
    scaled = int(floor * (1.0 + 2.0 * ratio))
    return max(floor, min(ceiling, scaled))


__all__ = [
    "TimeoutError",
    "DynamicTimeout",
    "operation_timeout",
    "with_pipeline_timeout",
    "adaptive_interval",
    "fast_timeout",
    "slow_timeout",
    "overrun_count",
    "reset_overruns",
    "BASE_TIMEOUT",
    "SLOW_TIMEOUT",
    "MAX_TIMEOUT",
    "TELEMETRY_INTERVAL",
    "CHART_REFRESH_MS",
    "STREAM_REFRESH_MS",
    "HEARTBEAT_MS",
    "CLOCK_MS",
    "FRAME_INTERVAL_MS",
]