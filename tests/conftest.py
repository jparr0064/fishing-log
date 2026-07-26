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
def _clear_caches():
    """Reset every layer of memoisation between tests.

    Three separate caches have to go, and missing any one produces a failure
    that only appears when tests run in sequence:

    * analytics' two base frames, keyed by (user_email, cache_version)
    * app.py's @st.cache_data page wrappers, keyed the same way — a test that
      renders an empty account for a given email poisons the next test that
      uses that email against a freshly seeded database
    * @st.cache_resource, which holds app._bootstrap

    Real deployments never hit this: the database does not change identity
    under a running process, which is exactly what these tests do every time.
    """
    import streamlit as st
    from fishing_log import analytics, database as db

    def _clear():
        analytics._session_frame_cached.clear()
        analytics._fish_frame_cached.clear()
        db._trip_uuid_support.clear()
        db._fallback_cache_ver = 0
        try:
            st.cache_data.clear()
            st.cache_resource.clear()
        except Exception:
            pass  # no runtime in some contexts; the explicit clears above hold

    _clear()
    yield
    _clear()
