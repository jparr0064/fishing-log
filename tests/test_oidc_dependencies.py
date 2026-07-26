"""Guard the Google sign-in dependency chain.

This file exists because of a production outage on 2026-07-26.

Upgrading Authlib 1.6.5 -> 1.6.12 was correct — 1.6.5 carried nine advisories,
including one where a JWT with alg:none passed signature verification. But
1.6.12's ``starlette_client/__init__`` imports ``httpx_client`` eagerly, and
httpx was not in requirements.txt. Authlib declares it as an optional extra and
1.6.5 imported it lazily, so nothing had ever needed it.

The result: the app deployed and ran fine, then returned a 500 the instant
anyone pressed "Sign in with Google" — ModuleNotFoundError: No module named
'httpx', raised deep inside streamlit's OAuth client builder.

Nothing caught it before production, and the reason is structural: local
development runs the typed-email form (app_env=development, auth_mode=local),
so the OIDC code path is never imported on a developer machine. Every test
passed. The app booted. Only a real Google sign-in touched it.

These tests import exactly what streamlit imports when a user clicks that
button, so the chain is verified on every run — no browser, no OAuth round
trip, no production required.
"""
from __future__ import annotations

import importlib

import pytest


def test_authlib_starlette_client_imports():
    """The precise import streamlit makes in _create_oauth_client.

    See streamlit/web/server/starlette/starlette_auth_routes.py:
        from authlib.integrations import starlette_client
    """
    module = importlib.import_module("authlib.integrations.starlette_client")
    assert hasattr(module, "OAuth"), "starlette_client must expose OAuth"


def test_httpx_is_installed():
    """Authlib's starlette integration imports httpx transitively.

    It is an optional Authlib extra, so it has to be requested explicitly in
    requirements.txt — nothing else pulls it in.
    """
    httpx = importlib.import_module("httpx")
    assert hasattr(httpx, "AsyncClient")


def test_authlib_httpx_client_imports():
    """The middle link in the chain, and where the outage actually surfaced."""
    module = importlib.import_module("authlib.integrations.httpx_client")
    assert hasattr(module, "AsyncOAuth1Client")


def test_requirements_declares_httpx():
    """Installed-but-undeclared is how this bug got to production.

    httpx being importable in a developer venv proves nothing about Cloud,
    which installs strictly from requirements.txt.
    """
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "requirements.txt"), encoding="utf-8") as fh:
        body = fh.read().lower()
    assert "httpx" in body, "httpx must be declared, not merely installed"


@pytest.mark.parametrize("module_name", [
    "authlib.jose",              # JWT/JWS verification
    "authlib.oauth2",            # OAuth2 client
    "authlib.integrations.base_client",
])
def test_remaining_authlib_surface_imports(module_name):
    """Catch any other lazily-imported dependency a future bump introduces."""
    importlib.import_module(module_name)
