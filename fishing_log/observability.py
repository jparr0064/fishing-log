"""Structured logging, audit events, and health signals (CR-10).

Three jobs:

* give every log line a machine-readable shape so a failure can actually be
  found in Streamlit Cloud's log viewer, which is a flat text stream
* record *that* a backup or restore happened, and how much moved, without ever
  writing a member's trip contents or coordinates into a log
* count failures so the owner sees a warning in the sidebar when something is
  failing repeatedly, rather than learning about it from a club member

Deliberately small. This is one Streamlit app on Community Cloud, not a fleet —
there is no metrics backend to ship to, so "monitoring" here means a health
panel the owner can read and a log line an owner can grep.

PRIVACY RULE, and the reason `audit()` takes keyword fields rather than a
message string: **no field value that could carry user content is logged.**
Counts, durations, booleans, and identifiers only. A trip note or a latitude in
a log file is the same disclosure as a trip note in a database, except logs are
retained by a third party and are not covered by "delete my data".
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager

_log = logging.getLogger("fishing_log")

# Field names that must never be logged, whatever a caller passes. Belt and
# braces: audit() is keyword-only, so this catches a future caller who adds one
# of these by name without thinking about it.
_FORBIDDEN_FIELDS = frozenset({
    "notes", "note", "latitude", "longitude", "lat", "lon", "coords",
    "coordinates", "location", "location_name", "label", "species",
    "bait_lure", "password", "database_url", "token", "secret", "email",
})

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Install a consistent format once per process.

    Streamlit configures the root logger itself, so this only adds a handler if
    nothing has claimed one — otherwise every line would be emitted twice.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
    _log.setLevel(level)


def new_correlation_id() -> str:
    """A short id that ties a user-facing error to its log line."""
    return uuid.uuid4().hex[:8].upper()


def _render(event: str, fields: dict) -> str:
    parts = [f"event={event}"]
    for key in sorted(fields):
        if key.lower() in _FORBIDDEN_FIELDS:
            parts.append(f"{key}=<redacted>")
            continue
        value = fields[key]
        # Only ever emit scalars. A dict or a DataFrame could carry anything.
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value)
            if isinstance(value, str) and (" " in text or "=" in text):
                text = f'"{text}"'
            parts.append(f"{key}={text}")
        else:
            parts.append(f"{key}=<{type(value).__name__}>")
    return " ".join(parts)


def audit(event: str, **fields) -> None:
    """Record that something notable happened. Counts and ids only."""
    _log.info(_render(event, fields))


def failure(event: str, *, correlation_id: str, exc: BaseException | None = None,
            **fields) -> None:
    """Record a failure with its traceback, tied to a correlation id.

    The exception's *message* is never rendered into the summary line — a
    driver error can quote a connection string. The traceback goes to the log
    body via exc_info, which the owner reads deliberately; the summary line
    stays safe to skim.
    """
    fields["correlation_id"] = correlation_id
    if exc is not None:
        fields["error_type"] = type(exc).__name__
    _record_failure(event)
    _log.error(_render(event, fields), exc_info=exc)


# ---------------------------------------------------------------------------
# Failure counting — the "alert the owner on repeated failures" half of CR-10
# ---------------------------------------------------------------------------

ALERT_THRESHOLD = 3       # failures within the window before the owner is told
ALERT_WINDOW_SECONDS = 900  # 15 minutes

# Process-local. Community Cloud runs one process, and a restart clearing this
# is correct: a restart is itself the remedy for most of what lands here.
_failures: list = []


def _record_failure(event: str) -> None:
    now = time.monotonic()
    _failures.append((now, event))
    cutoff = now - ALERT_WINDOW_SECONDS
    while _failures and _failures[0][0] < cutoff:
        _failures.pop(0)


def recent_failures() -> list:
    """(seconds_ago, event) for failures inside the alert window, newest last."""
    now = time.monotonic()
    cutoff = now - ALERT_WINDOW_SECONDS
    return [(int(now - t), e) for t, e in _failures if t >= cutoff]


def should_alert_owner() -> bool:
    return len(recent_failures()) >= ALERT_THRESHOLD


def reset_failures() -> None:
    """For tests, and for the owner dismissing an alert after investigating."""
    _failures.clear()


@contextmanager
def timed(event: str, **fields):
    """Audit an operation with its duration, whether or not it succeeds."""
    started = time.monotonic()
    correlation_id = new_correlation_id()
    try:
        yield correlation_id
    except Exception as exc:
        failure(f"{event}.failed", correlation_id=correlation_id, exc=exc,
                ms=int((time.monotonic() - started) * 1000), **fields)
        raise
    else:
        audit(event, correlation_id=correlation_id,
              ms=int((time.monotonic() - started) * 1000), **fields)


# ---------------------------------------------------------------------------
# Connection pool health
# ---------------------------------------------------------------------------

def pool_stats(engine) -> dict:
    """Connection pool counters, or {} when the pool does not expose them.

    "No exhausted database connection pool" is one of the review's service
    targets, and the pool is sized at 5 with 10 overflow — worth being able to
    see during a club-scale test rather than inferring it from timeouts.
    """
    try:
        pool = engine.pool
        size = pool.size()
        checked_out = pool.checkedout()

        # pool.overflow() counts connections created BEYOND pool_size, and it
        # starts at -pool_size — so a fresh pool reports -4, not 0. Reporting it
        # raw renders as "+-4 overflow". Clamp for display; the negative value
        # only means the pool has not filled yet.
        overflow = max(0, pool.overflow())

        # Capacity is pool_size + max_overflow, not the current overflow. Using
        # the current value would call a healthy idle pool "exhausted" the
        # instant checked_out reached pool_size, long before it actually was.
        max_overflow = getattr(pool, "_max_overflow", 0)
        capacity = size + max(0, max_overflow)

        return {
            "size": size,
            "checked_out": checked_out,
            "overflow": overflow,
            "capacity": capacity,
            "exhausted": capacity > 0 and checked_out >= capacity,
        }
    except Exception:
        # SQLite's pool in tests exposes a different surface; not worth raising.
        return {}
