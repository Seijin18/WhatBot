"""Instagram OAuth/credential-lifecycle HTTP calls.

Separate from `whatbot/channels/instagram.py` (outbound message sending):
this module is setup/maintenance plumbing (authorize, exchange, refresh,
subscribe), used by `scripts/ig_oauth.py`, `scripts/ig_refresh_token.py`,
`scripts/ig_subscribe_webhook.py`, `scripts/ig_health_check.py` and
`windmill/f/whatbot/refresh_ig_token.py` — never by the request-time send
path. Endpoints and flow per
`docs/INSTAGRAM_INTEGRATION_PLAN.md` section 3 ("Token") and
`whatbot/channels/instagram.py`'s docstring (Instagram API with Instagram
Login, host `graph.instagram.com`, not the Facebook Login variant).

Pure HTTP wrappers: every function takes its inputs explicitly and returns
the parsed JSON body (raising `requests.HTTPError` on a non-2xx response) —
no hidden globals, no `whatbot/db.py` dependency, so each is testable with a
mocked `requests`.
"""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import urlencode

import requests

AUTHORIZE_BASE_URL = "https://www.instagram.com/oauth/authorize"
SHORT_TOKEN_BASE_URL = "https://api.instagram.com"
GRAPH_BASE_URL = "https://graph.instagram.com"
API_VERSION = "v23.0"

# `instagram_business_basic` + `instagram_business_manage_messages`: the
# scopes still valid after the 2025-01-27 deprecation of the unprefixed
# names (`business_basic`, `business_manage_messages`) — see the plan doc.
DEFAULT_SCOPES = ("instagram_business_basic", "instagram_business_manage_messages")


def authorize_url(
    client_id: str,
    redirect_uri: str,
    *,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    state: str | None = None,
) -> str:
    """URL the admin opens in a browser to grant access to the account."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(scopes),
        "response_type": "code",
    }
    if state:
        params["state"] = state
    return f"{AUTHORIZE_BASE_URL}?{urlencode(params)}"


def exchange_code_for_short_token(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    *,
    base_url: str = SHORT_TOKEN_BASE_URL,
) -> Dict[str, Any]:
    """Trade the one-time authorization `code` for a short-lived token.

    `code` is single-use and expires in 1 hour, per the Meta flow.
    """
    response = requests.post(
        f"{base_url}/oauth/access_token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def exchange_for_long_lived_token(
    short_lived_token: str,
    client_secret: str,
    *,
    base_url: str = GRAPH_BASE_URL,
) -> Dict[str, Any]:
    """Trade a short-lived token for a long-lived one (valid ~60 days)."""
    response = requests.get(
        f"{base_url}/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": client_secret,
            "access_token": short_lived_token,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def refresh_long_lived_token(
    access_token: str, *, base_url: str = GRAPH_BASE_URL
) -> Dict[str, Any]:
    """Refresh a long-lived token before it expires (resets the 60-day clock).

    Requirement "Renovação automática de credencial": must run before
    expiry — the token cannot be refreshed once it has already expired.
    """
    response = requests.get(
        f"{base_url}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": access_token},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def subscribe_webhook(
    access_token: str,
    *,
    base_url: str = GRAPH_BASE_URL,
    api_version: str = API_VERSION,
    subscribed_fields: str = "messages",
) -> Dict[str, Any]:
    """Subscribe the account to webhook delivery for `subscribed_fields`."""
    response = requests.post(
        f"{base_url}/{api_version}/me/subscribed_apps",
        params={"subscribed_fields": subscribed_fields, "access_token": access_token},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_subscribed_apps(
    access_token: str, *, base_url: str = GRAPH_BASE_URL, api_version: str = API_VERSION
) -> Dict[str, Any]:
    response = requests.get(
        f"{base_url}/{api_version}/me/subscribed_apps",
        params={"access_token": access_token},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_account_info(
    access_token: str, *, base_url: str = GRAPH_BASE_URL, api_version: str = API_VERSION
) -> Dict[str, Any]:
    response = requests.get(
        f"{base_url}/{api_version}/me",
        params={"fields": "id,username", "access_token": access_token},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()
