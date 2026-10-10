"""Google sign-in: OAuth 2.0 authorization code flow with PKCE.

Configured by `BREAKPOINT_GOOGLE_CLIENT_ID`, `BREAKPOINT_GOOGLE_CLIENT_SECRET`
and `BREAKPOINT_GOOGLE_REDIRECT_URI`. Until all three exist the feature
reports itself unavailable and the button never appears - the same rule the
SSO adapter follows, because a sign-in button that cannot work is worse than
no button.

Why this shape:

  * **PKCE** as well as the client secret. The secret alone protects a
    confidential client; the verifier also protects against an authorization
    code intercepted at the redirect.
  * **State and nonce live in the database** (OAuthHandshake), not in a
    cookie, and are consumed on first use. A replayed callback finds a used
    row and is refused.
  * **The ID token is read, not trusted blindly.** It arrives over TLS from
    Google's own token endpoint, which is what lets us skip JWKS signature
    verification (Google documents this for the direct exchange), so the
    checks that remain - issuer, audience, expiry, nonce - are the ones doing
    the work here and are all enforced below.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.accounts import GoogleProfile
from app.config import settings
from app.models import OAuthHandshake

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
SCOPES = "openid email profile"
HANDSHAKE_TTL_MINUTES = 10
HTTP_TIMEOUT = 10.0
# Clock skew allowed on the ID token's expiry.
LEEWAY_SECONDS = 30


class GoogleError(Exception):
    """Sign-in through Google failed. Safe to show a student."""


def missing_configuration() -> list[str]:
    missing = []
    if not settings.google_client_id:
        missing.append("BREAKPOINT_GOOGLE_CLIENT_ID")
    if not settings.google_client_secret:
        missing.append("BREAKPOINT_GOOGLE_CLIENT_SECRET")
    if not settings.google_redirect_uri:
        missing.append("BREAKPOINT_GOOGLE_REDIRECT_URI")
    return missing


def is_configured() -> bool:
    return not missing_configuration()


@dataclass(frozen=True)
class Handshake:
    state: str
    nonce: str
    code_verifier: str


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


def begin(session: Session) -> tuple[str, Handshake]:
    """Record a handshake and return the Google URL to send the browser to."""
    if not is_configured():
        raise GoogleError(
            "Google sign-in is not configured on this server: missing "
            + ", ".join(missing_configuration())
        )
    purge_expired(session)
    verifier, challenge = _pkce_pair()
    handshake = Handshake(
        state=secrets.token_urlsafe(24),
        nonce=secrets.token_urlsafe(24),
        code_verifier=verifier,
    )
    now = datetime.now(UTC)
    session.add(
        OAuthHandshake(
            state=handshake.state,
            nonce=handshake.nonce,
            code_verifier=handshake.code_verifier,
            created_at=now,
            expires_at=now + timedelta(minutes=HANDSHAKE_TTL_MINUTES),
        )
    )
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": handshake.state,
            "nonce": handshake.nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Ask for the account chooser rather than silently reusing
            # whichever Google account the browser happens to hold.
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZE_URL}?{query}", handshake


def take_handshake(session: Session, state: str) -> OAuthHandshake:
    """Consume the handshake for `state`, or raise."""
    record = session.scalar(select(OAuthHandshake).where(OAuthHandshake.state == state))
    if record is None:
        raise GoogleError("This sign-in link is not one we started. Try again.")
    if record.used_at is not None:
        raise GoogleError("This sign-in link has already been used. Try again.")
    if _aware(record.expires_at) <= datetime.now(UTC):
        raise GoogleError("This sign-in took too long. Try again.")
    record.used_at = datetime.now(UTC)
    return record


def exchange_code(code: str, code_verifier: str) -> dict[str, Any]:
    """Trade the authorization code for tokens at Google's token endpoint."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise GoogleError(f"Could not reach Google to complete sign-in: {exc}") from exc
    if response.status_code != 200:
        raise GoogleError(
            "Google refused the sign-in exchange "
            f"({response.status_code}). Check the client id, secret and "
            "redirect URI."
        )
    return response.json()


def _decode_segment(segment: str) -> dict[str, Any]:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))


def profile_from_id_token(id_token: str, *, nonce: str) -> GoogleProfile:
    """Read and check the ID token returned by the token endpoint."""
    parts = id_token.split(".")
    if len(parts) != 3:
        raise GoogleError("Google returned a malformed ID token.")
    try:
        claims = _decode_segment(parts[1])
    except (ValueError, json.JSONDecodeError) as exc:
        raise GoogleError("Google returned an unreadable ID token.") from exc

    if claims.get("iss") not in ISSUERS:
        raise GoogleError("That ID token was not issued by Google.")
    audience = claims.get("aud")
    if audience != settings.google_client_id:
        raise GoogleError("That ID token was issued for a different application.")
    if claims.get("nonce") != nonce:
        raise GoogleError("That sign-in response does not match the request.")
    expiry = int(claims.get("exp", 0))
    if expiry + LEEWAY_SECONDS < int(datetime.now(UTC).timestamp()):
        raise GoogleError("That sign-in response has expired. Try again.")

    subject = str(claims.get("sub") or "")
    if not subject:
        raise GoogleError("Google did not identify the account.")
    return GoogleProfile(
        subject=subject,
        email=str(claims.get("email") or ""),
        name=str(claims.get("name") or ""),
        email_verified=bool(claims.get("email_verified")),
    )


def purge_expired(session: Session) -> int:
    """Drop handshakes nobody completed. Returns how many were removed."""
    stale = session.scalars(
        select(OAuthHandshake).where(OAuthHandshake.expires_at < datetime.now(UTC))
    ).all()
    for row in stale:
        session.delete(row)
    return len(stale)


def status() -> dict[str, Any]:
    return {
        "configured": is_configured(),
        "missing_settings": missing_configuration(),
        "redirect_uri": settings.google_redirect_uri if is_configured() else None,
    }


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
