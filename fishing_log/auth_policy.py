"""Authentication policy — who may sign in, and by which route.

Pure decision logic with **no Streamlit import**, so the whole auth matrix is
unit-testable without a running app. ``app.py`` reads the raw configuration and
the signed-in identity, hands them here, and renders whatever this module says.

The rule this module exists to enforce: the typed-email form is a *development*
convenience and nothing else. It is permitted only when the deployment both
declares itself development **and** explicitly selects local auth. Every other
combination — including missing, unknown, or malformed configuration — resolves
to OIDC, and OIDC that is not configured resolves to a hard error rather than a
fallback.

This replaces a ``try/except`` runtime probe that treated *any* exception as
"OIDC unavailable" and silently downgraded production to a form where a visitor
could type any address and read that person's trips.
"""
from __future__ import annotations

from typing import NamedTuple

# ---- Configuration vocabulary --------------------------------------------

PRODUCTION = "production"
DEVELOPMENT = "development"

MODE_OIDC = "oidc"
MODE_LOCAL = "local"

# ---- Resolved auth modes --------------------------------------------------

AUTH_OIDC = "oidc"    # require Google sign-in
AUTH_LOCAL = "local"  # typed-email form permitted (development only)
AUTH_ERROR = "error"  # misconfigured — admit nobody

# ---- Resolved identity outcomes ------------------------------------------

OUTCOME_ERROR = "error"                # show the maintenance page
OUTCOME_LOGIN_REQUIRED = "login"       # show the sign-in page for `mode`
OUTCOME_NOT_APPROVED = "not_approved"  # authenticated, but not on the allowlist
OUTCOME_ALLOWED = "allowed"            # proceed as `email`


class AuthResult(NamedTuple):
    """The complete auth decision for one app run.

    ``reason`` is a human-readable, **secret-free** line for the server log. It
    may be present even on a successful outcome (configuration warnings).
    """

    outcome: str
    mode: str
    email: str
    reason: str | None


def normalize_env(raw: object) -> str:
    """Coerce APP_ENV to a known value.

    Anything unrecognised — including empty, ``None``, or a typo like
    ``"prod"`` — becomes production. Guessing wrong in the safe direction only
    costs a developer an explicit setting; guessing wrong the other way exposes
    real users' data.
    """
    return DEVELOPMENT if str(raw or "").strip().lower() == DEVELOPMENT else PRODUCTION


def normalize_mode(raw: object) -> str:
    """Coerce AUTH_MODE to a known value. Anything unrecognised becomes oidc."""
    return MODE_LOCAL if str(raw or "").strip().lower() == MODE_LOCAL else MODE_OIDC


def normalize_email(raw: object) -> str:
    """Lowercase and strip an email for comparison. Non-strings become ''."""
    if raw is None or isinstance(raw, bool):
        return ""
    return str(raw).strip().lower()


def allowed_emails(allowed_raw: object, owner_email: object) -> set[str]:
    """The approved-account allowlist, lowercased.

    ``allowed_raw`` is the ``allowed_emails`` secret: a list, or a
    comma-separated string. The owner (``dev_user_email``) is always included,
    so an absent allowlist means "only the owner" rather than "everyone".
    """
    raw = allowed_raw or []
    if isinstance(raw, str):
        raw = raw.split(",")
    allowed = {normalize_email(entry) for entry in raw}
    allowed.discard("")
    owner = normalize_email(owner_email)
    if owner:
        allowed.add(owner)
    return allowed


def is_allowed(email: object, allowed_raw: object, owner_email: object) -> bool:
    """Whether this address may hold a real account."""
    candidate = normalize_email(email)
    return bool(candidate) and candidate in allowed_emails(allowed_raw, owner_email)


def resolve_auth(app_env: object, auth_mode: object, oidc_configured: bool):
    """Decide which login route is permitted.

    Returns ``(mode, reason)`` where mode is :data:`AUTH_OIDC`,
    :data:`AUTH_LOCAL`, or :data:`AUTH_ERROR`, and reason is a secret-free log
    line (or ``None``).
    """
    env = normalize_env(app_env)
    mode = normalize_mode(auth_mode)

    # The one and only path to the typed-email form.
    if env == DEVELOPMENT and mode == MODE_LOCAL:
        return AUTH_LOCAL, None

    warning = None
    if env == PRODUCTION and mode == MODE_LOCAL:
        warning = ("AUTH_MODE=local requested while APP_ENV=production — "
                   "ignoring it and requiring OIDC.")

    if oidc_configured:
        return AUTH_OIDC, warning

    if env == DEVELOPMENT:
        reason = ("Development deployment selected AUTH_MODE=oidc but no [auth] "
                  "block is configured. Set auth_mode=\"local\" for the "
                  "typed-email form.")
    else:
        reason = ("Production deployment has no usable [auth] configuration. "
                  "Refusing to fall back to the typed-email form.")
    return AUTH_ERROR, reason


def resolve_identity(
    *,
    app_env: object,
    auth_mode: object,
    oidc_configured: bool,
    is_logged_in: bool,
    email: object = "",
    allowed_raw: object = None,
    owner_email: object = "",
) -> AuthResult:
    """Resolve configuration plus a signed-in identity into one decision.

    The allowlist is applied to OIDC identities only; local mode is already
    gated behind an explicit development declaration and has no real identity
    to approve.
    """
    mode, reason = resolve_auth(app_env, auth_mode, oidc_configured)

    if mode == AUTH_ERROR:
        return AuthResult(OUTCOME_ERROR, AUTH_ERROR, "", reason)

    if not is_logged_in:
        return AuthResult(OUTCOME_LOGIN_REQUIRED, mode, "", reason)

    candidate = normalize_email(email)
    if not candidate:
        # Authenticated but with no usable address — treat as signed out rather
        # than admitting an empty identity that would scope queries to ''.
        return AuthResult(
            OUTCOME_LOGIN_REQUIRED, mode, "",
            reason or "Signed-in identity carried no email address.",
        )

    if mode == AUTH_OIDC and not is_allowed(candidate, allowed_raw, owner_email):
        return AuthResult(OUTCOME_NOT_APPROVED, mode, candidate, reason)

    return AuthResult(OUTCOME_ALLOWED, mode, candidate, reason)
