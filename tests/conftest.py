"""Shared pytest setup.

Analytics memoises its two base frames with st.cache_data, keyed by
(user_email, cache_version). Every test uses the same TEST_EMAIL and starts at
version 0, so without this the first test's data would be served to every test
after it — each of which builds a brand new in-memory database. Clearing around
each test keeps them independent.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def _clear_analytics_cache():
    from fishing_log import analytics, database as db

    def _clear():
        analytics._session_frame_cached.clear()
        analytics._fish_frame_cached.clear()
        db._trip_uuid_support.clear()

    _clear()
    yield
    _clear()
