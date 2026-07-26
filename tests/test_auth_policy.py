"""Tests for CR-1 — production authentication must fail closed.

Covers the five states named in the change request: approved, unapproved,
signed-out, misconfigured-production, and local-development. These exercise
``fishing_log.auth_policy`` directly; it has no Streamlit dependency, so the
whole matrix runs without a live app. The Streamlit-level wiring (which page
actually renders) is covered separately by the CR-6 integration tests.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import auth_policy as ap  # noqa: E402

OWNER = "owner@example.com"
APPROVED = "member@example.com"
STRANGER = "stranger@example.com"


def _identity(**overrides):
    """resolve_identity with a signed-in approved user as the baseline."""
    kwargs = dict(
        app_env="production",
        auth_mode="oidc",
        oidc_configured=True,
        is_logged_in=True,
        email=APPROVED,
        allowed_raw=[APPROVED],
        owner_email=OWNER,
    )
    kwargs.update(overrides)
    return ap.resolve_identity(**kwargs)


# ---- Normalisation: unknown config must land on the safe side -------------

@pytest.mark.parametrize("raw", ["development", "  Development  ", "DEVELOPMENT"])
def test_development_recognised_case_and_space_insensitively(raw):
    assert ap.normalize_env(raw) == ap.DEVELOPMENT


@pytest.mark.parametrize("raw", ["", None, "prod", "dev", "staging", "PRODUCTION", 0, []])
def test_unrecognised_env_is_production(raw):
    """A typo must not silently unlock the dev login path."""
    assert ap.normalize_env(raw) == ap.PRODUCTION


@pytest.mark.parametrize("raw", ["", None, "OIDC", "google", "locale", "LOCAL "])
def test_unrecognised_mode_is_oidc(raw):
    assert ap.normalize_mode(raw) == (
        ap.MODE_LOCAL if str(raw).strip().lower() == "local" else ap.MODE_OIDC
    )


# ---- Misconfigured production: nobody gets in ----------------------------

def test_production_without_oidc_is_an_error_not_a_form():
    """The core regression: no [auth] in production must NOT yield local auth."""
    mode, reason = ap.resolve_auth("production", "oidc", oidc_configured=False)
    assert mode == ap.AUTH_ERROR
    assert mode != ap.AUTH_LOCAL
    assert reason and "typed-email" in reason


def test_production_cannot_opt_into_local_auth():
    """Even an explicit auth_mode=local is ignored when APP_ENV=production."""
    mode, reason = ap.resolve_auth("production", "local", oidc_configured=True)
    assert mode == ap.AUTH_OIDC
    assert reason and "ignoring it" in reason


def test_production_local_mode_without_oidc_still_errors():
    mode, _ = ap.resolve_auth("production", "local", oidc_configured=False)
    assert mode == ap.AUTH_ERROR


def test_unset_config_defaults_to_requiring_oidc():
    """An operator who configures nothing gets the safe behaviour by default."""
    assert ap.resolve_auth("", "", oidc_configured=False)[0] == ap.AUTH_ERROR
    assert ap.resolve_auth("", "", oidc_configured=True)[0] == ap.AUTH_OIDC


def test_misconfigured_production_admits_nobody_even_when_signed_in():
    result = _identity(oidc_configured=False)
    assert result.outcome == ap.OUTCOME_ERROR
    assert result.email == ""


def test_error_reason_carries_no_secret_values():
    _, reason = ap.resolve_auth("production", "oidc", oidc_configured=False)
    lowered = reason.lower()
    assert "postgres" not in lowered and "password" not in lowered
    assert "@" not in reason


# ---- Local development: the one permitted path to the email form ---------

def test_development_plus_local_permits_the_email_form():
    mode, reason = ap.resolve_auth("development", "local", oidc_configured=False)
    assert mode == ap.AUTH_LOCAL
    assert reason is None


def test_development_defaults_to_oidc_without_an_explicit_local_mode():
    """APP_ENV=development alone is not enough — AUTH_MODE must say so too."""
    assert ap.resolve_auth("development", "", oidc_configured=False)[0] == ap.AUTH_ERROR


def test_local_mode_skips_the_allowlist():
    """Dev convenience: any address works locally, but only locally."""
    result = _identity(
        app_env="development", auth_mode="local", oidc_configured=False,
        email=STRANGER, allowed_raw=[],
    )
    assert result.outcome == ap.OUTCOME_ALLOWED
    assert result.email == STRANGER


def test_local_mode_signed_out_asks_for_login():
    result = _identity(
        app_env="development", auth_mode="local", oidc_configured=False,
        is_logged_in=False, email="",
    )
    assert result.outcome == ap.OUTCOME_LOGIN_REQUIRED
    assert result.mode == ap.AUTH_LOCAL


# ---- Signed out ----------------------------------------------------------

def test_signed_out_in_production_gets_the_oidc_login_page():
    result = _identity(is_logged_in=False, email="")
    assert result.outcome == ap.OUTCOME_LOGIN_REQUIRED
    assert result.mode == ap.AUTH_OIDC
    assert result.email == ""


def test_logged_in_flag_without_an_email_is_treated_as_signed_out():
    """Never admit an empty identity — it would scope every query to ''."""
    for empty in ("", None, "   "):
        result = _identity(email=empty)
        assert result.outcome == ap.OUTCOME_LOGIN_REQUIRED
        assert result.email == ""


# ---- Approved / unapproved ----------------------------------------------

def test_approved_user_is_allowed():
    result = _identity()
    assert result.outcome == ap.OUTCOME_ALLOWED
    assert result.email == APPROVED


def test_owner_is_always_allowed_even_with_an_empty_allowlist():
    result = _identity(email=OWNER, allowed_raw=[])
    assert result.outcome == ap.OUTCOME_ALLOWED


def test_unapproved_google_account_is_refused():
    result = _identity(email=STRANGER)
    assert result.outcome == ap.OUTCOME_NOT_APPROVED
    assert result.email == STRANGER


def test_absent_allowlist_admits_only_the_owner():
    assert ap.allowed_emails(None, OWNER) == {OWNER}
    assert not ap.is_allowed(STRANGER, None, OWNER)


def test_allowlist_accepts_a_comma_separated_string():
    allowed = ap.allowed_emails(f" {APPROVED} , {STRANGER} ", OWNER)
    assert allowed == {APPROVED, STRANGER, OWNER}


def test_allowlist_comparison_ignores_case_and_whitespace():
    assert ap.is_allowed("  MeMbEr@Example.COM  ", [APPROVED], OWNER)


def test_allowlist_ignores_blank_entries():
    assert ap.allowed_emails(["", "   ", None, APPROVED], "") == {APPROVED}


def test_empty_email_is_never_allowed():
    assert not ap.is_allowed("", [APPROVED], OWNER)
    assert not ap.is_allowed(None, [APPROVED], OWNER)
