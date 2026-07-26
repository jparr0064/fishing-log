"""Tests for CR-10 — audit logging that never leaks trip contents.

The point of an audit trail here is to record *that* a backup or restore
happened and how much moved. A trip note or a latitude written into a log is
the same disclosure as one written into the database, except logs live with a
third party and are not covered by "delete my data". These pin that boundary,
plus the failure counting behind the owner's health alert.
"""
from __future__ import annotations

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import observability as obs  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    obs.reset_failures()
    yield
    obs.reset_failures()


# ---- Nothing private reaches a log line ---------------------------------

@pytest.mark.parametrize("field", [
    "notes", "latitude", "longitude", "location_name", "species",
    "bait_lure", "email", "password", "database_url", "token",
])
def test_private_fields_are_redacted(field, caplog):
    with caplog.at_level(logging.INFO, logger="fishing_log"):
        obs.audit("backup.exported", **{field: "SECRET-VALUE-1234"})
    text = caplog.text
    assert "SECRET-VALUE-1234" not in text, f"{field} leaked its value"
    assert f"{field}=<redacted>" in text


def test_counts_and_ids_are_kept(caplog):
    with caplog.at_level(logging.INFO, logger="fishing_log"):
        obs.audit("backup.exported", trips=15, fish=50, bytes=4096, version=2)
    text = caplog.text
    assert "trips=15" in text and "fish=50" in text
    assert "bytes=4096" in text and "version=2" in text


def test_non_scalar_values_are_reduced_to_their_type(caplog):
    """A dict or a DataFrame could carry anything, so never render it."""
    with caplog.at_level(logging.INFO, logger="fishing_log"):
        obs.audit("restore.attempted",
                  payload={"notes": "caught a big one at my secret cove"})
    assert "secret cove" not in caplog.text
    assert "payload=<dict>" in caplog.text


def test_failure_line_omits_the_exception_message(caplog):
    """A driver error can quote the connection string; only the type is safe."""
    exc = RuntimeError("could not connect: postgres://user:hunter2@db.internal")
    with caplog.at_level(logging.ERROR, logger="fishing_log"):
        obs.failure("write.add_session", correlation_id="ABC12345", exc=exc)

    summary = [r.getMessage() for r in caplog.records][0]
    assert "hunter2" not in summary
    assert "db.internal" not in summary
    assert "error_type=RuntimeError" in summary
    assert "correlation_id=ABC12345" in summary


def test_traceback_is_still_captured_for_the_owner(caplog):
    with caplog.at_level(logging.ERROR, logger="fishing_log"):
        obs.failure("write.x", correlation_id="ABC12345",
                    exc=ValueError("boom"))
    assert caplog.records[0].exc_info is not None, "owner needs the traceback"


# ---- Correlation ids ----------------------------------------------------

def test_correlation_ids_are_short_and_unique():
    ids = {obs.new_correlation_id() for _ in range(200)}
    assert len(ids) == 200
    # Uppercase hex. Not `.isupper()`, which is False for an all-digit id
    # because it contains no cased characters at all.
    assert all(len(i) == 8 for i in ids)
    assert all(i == i.upper() for i in ids)
    assert all(set(i) <= set("0123456789ABCDEF") for i in ids)


# ---- Failure counting drives the owner alert ----------------------------

def test_alert_fires_only_at_the_threshold():
    for i in range(obs.ALERT_THRESHOLD - 1):
        obs.failure("write.x", correlation_id=f"ID{i:06d}")
        assert obs.should_alert_owner() is False

    obs.failure("write.x", correlation_id="IDLAST00")
    assert obs.should_alert_owner() is True
    assert len(obs.recent_failures()) == obs.ALERT_THRESHOLD


def test_old_failures_fall_out_of_the_window(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(obs.time, "monotonic", lambda: clock["t"])

    for i in range(obs.ALERT_THRESHOLD):
        obs.failure("write.x", correlation_id=f"ID{i:06d}")
    assert obs.should_alert_owner() is True

    clock["t"] += obs.ALERT_WINDOW_SECONDS + 1
    assert obs.recent_failures() == []
    assert obs.should_alert_owner() is False, "a quiet hour must clear the alert"


def test_audit_does_not_count_as_a_failure():
    obs.audit("backup.exported", trips=1)
    assert obs.recent_failures() == []


def test_reset_clears_the_alert():
    for i in range(obs.ALERT_THRESHOLD):
        obs.failure("write.x", correlation_id=f"ID{i:06d}")
    obs.reset_failures()
    assert obs.should_alert_owner() is False


# ---- timed() ------------------------------------------------------------

def test_timed_audits_success_with_a_duration(caplog):
    with caplog.at_level(logging.INFO, logger="fishing_log"):
        with obs.timed("restore.run", trips=3) as cid:
            assert len(cid) == 8
    text = caplog.text
    assert "event=restore.run" in text and "ms=" in text and "trips=3" in text
    assert obs.recent_failures() == []


def test_timed_records_a_failure_and_reraises(caplog):
    with caplog.at_level(logging.ERROR, logger="fishing_log"):
        with pytest.raises(ValueError):
            with obs.timed("restore.run", trips=3):
                raise ValueError("boom")
    assert "event=restore.run.failed" in caplog.text
    assert len(obs.recent_failures()) == 1


# ---- Pool stats ---------------------------------------------------------

def test_pool_stats_returns_empty_rather_than_raising():
    class _Broken:
        @property
        def pool(self):
            raise RuntimeError("no pool here")

    assert obs.pool_stats(_Broken()) == {}


def _fake_engine(size, checked_out, overflow, max_overflow=10):
    class _Pool:
        _max_overflow = max_overflow

        def size(self):
            return size

        def checkedout(self):
            return checked_out

        def overflow(self):
            return overflow

    class _Engine:
        pool = _Pool()

    return _Engine()


def test_pool_stats_flags_exhaustion():
    # 15 of 15 (5 base + 10 overflow) checked out.
    stats = obs.pool_stats(_fake_engine(size=5, checked_out=15, overflow=10))
    assert stats["capacity"] == 15
    assert stats["exhausted"] is True


def test_pool_stats_reports_headroom_as_healthy():
    stats = obs.pool_stats(_fake_engine(size=5, checked_out=2, overflow=0))
    assert stats["exhausted"] is False


def test_a_full_base_pool_with_overflow_left_is_not_exhausted():
    """The bug this guards: capacity is base + max_overflow, not base alone.

    Using the current overflow count as capacity called a healthy pool
    exhausted the instant checked_out reached pool_size.
    """
    stats = obs.pool_stats(_fake_engine(size=5, checked_out=5, overflow=0))
    assert stats["capacity"] == 15
    assert stats["exhausted"] is False


def test_negative_overflow_is_never_displayed():
    """SQLAlchemy reports overflow as -pool_size on a fresh pool.

    Rendered raw that produced "(+-4 overflow)" in the sidebar.
    """
    stats = obs.pool_stats(_fake_engine(size=5, checked_out=0, overflow=-4))
    assert stats["overflow"] == 0
    assert stats["exhausted"] is False


def test_pool_without_max_overflow_attribute_still_works():
    class _Pool:
        def size(self):
            return 5

        def checkedout(self):
            return 5

        def overflow(self):
            return 0

    class _Engine:
        pool = _Pool()

    stats = obs.pool_stats(_Engine())
    assert stats["capacity"] == 5
    assert stats["exhausted"] is True
