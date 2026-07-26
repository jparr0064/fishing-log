"""Tests for CR-9 — user-authored text must not be interpreted as Markdown.

st.markdown, st.write and st.info all parse Markdown. Trip notes, location
names and bait names are free text an angler typed about a fish; none of them
are meant to be formatted, and a note containing a link renders as a live link
in whoever's browser opens that trip.

_plain() is imported from app.py, which pulls in Streamlit but does not need a
running server for these pure-function checks.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app  # noqa: E402


@pytest.mark.parametrize("payload", [
    "[free lures](http://evil.example)",
    "**Secret Spot**",
    "_italic_",
    "# Huge heading",
    "![img](http://evil.example/track.png)",
    "`code`",
    "> quote",
    "- bullet",
    "~~struck~~",
    "| table | row |",
])
def test_markdown_syntax_is_defused(payload):
    out = app._plain(payload)
    # Every metacharacter that was present is now backslash-escaped.
    for ch in payload:
        if ch in app._MD_SPECIAL:
            assert "\\" + ch in out, f"{ch!r} left unescaped in {out!r}"


def test_a_link_cannot_survive_escaping():
    out = app._plain("[click](http://evil.example)")
    assert "\\[" in out and "\\]" in out and "\\(" in out
    assert "[click](" not in out


def test_backslash_is_escaped_first_and_not_doubled():
    """Escaping '\\' after the others would corrupt the escapes just added."""
    assert app._plain("a\\b") == "a\\\\b"
    # A lone backslash before a metacharacter stays one escaped backslash plus
    # one escaped metacharacter — not a mangled pair.
    assert app._plain("\\*") == "\\\\\\*"


def test_plain_text_survives_unchanged():
    for benign in ["Caught 3 stripers", "SML Main Channel", "Live shad", ""]:
        assert app._plain(benign) == benign


def test_none_becomes_empty_string():
    assert app._plain(None) == ""


def test_numbers_and_dates_are_stringified_safely():
    assert app._plain(42) == "42"
    # A date contains '-' which is a metacharacter; it must escape, not vanish.
    assert app._plain("2026-07-04") == "2026\\-07\\-04"


# ---- Chart guards --------------------------------------------------------

def test_chart_ready_rejects_empty_and_missing():
    import pandas as pd

    assert app._chart_ready(None, "x") is False
    assert app._chart_ready(pd.DataFrame(), "x") is False
    assert app._chart_ready(pd.DataFrame({"y": [1]}), "x") is False, "missing column"


def test_chart_ready_rejects_all_nan_columns():
    """The case that produced Vega 'infinite extent' warnings in the console."""
    import numpy as np
    import pandas as pd

    df = pd.DataFrame({"month": ["Jan", "Feb"], "total": [np.nan, np.nan]})
    assert app._chart_ready(df, "total") is False


def test_chart_ready_accepts_partial_data():
    import numpy as np
    import pandas as pd

    df = pd.DataFrame({"month": ["Jan", "Feb"], "total": [np.nan, 5]})
    assert app._chart_ready(df, "total") is True


def test_chart_ready_requires_every_named_column():
    import numpy as np
    import pandas as pd

    df = pd.DataFrame({"a": [1, 2], "b": [np.nan, np.nan]})
    assert app._chart_ready(df, "a") is True
    assert app._chart_ready(df, "a", "b") is False
