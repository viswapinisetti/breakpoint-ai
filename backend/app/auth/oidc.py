"""OIDC bearer-token verification for NxtWave SSO (PRD sections 105, 12.5).

Breakpoint does not own identity - it consumes it. This module verifies an
access or ID token issued by NxtWave's identity provider and maps its claims
onto a Breakpoint user. The verification is real: discovery document, JWKS
fetch with key rotation, signature check, and issuer/audience/expiry
validation. Nothing here trusts a claim it has not checked.

**Status: implemented but unwired.** PRD v0.2 section 12.5 says not to claim a
working integration without credentials and an API contract, and we have
neither. Three configuration values are missing and cannot be guessed:

    BREAKPOINT_OIDC_ISSUER          the issuer URL (discovery is derived from it)
    BREAKPOINT_OIDC_AUDIENCE        the audience this API is registered under
    BREAKPOINT_OIDC_SUBJECT_CLAIM   which claim carries the stable student id

Until `BREAKPOINT_AUTH_MODE=oidc` is set with those present, the app runs in
header mode and this module is inert. `python -m scripts.auth_check` reports
exactly which values are missing and what will happen when they are supplied.

Two deliberate design decisions worth stating:

* **The subject claim is configuration, not a guess.** Providers differ on
  which claim is the durable identifier (`sub`, `preferred_username`, a
  tenant-specific `student_id`). Picking one and hoping is how accounts get
  merged or duplicated, so this refuses to start in OIDC mode without being
  told.
* **Failures are 401, never a fallback to header mode.** A misconfigured
  verifier that silently accepts `X-Student-Id` is worse than one that rejects
  everything, because it looks like it works.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# How long a fetched JWKS is reused before refetching. Short enough that a key
# rotation heals without a restart, long enough not to hit the IdP per request.
JWKS_TTL_SECONDS = 600
# Allowance for clock skew between this host and the IdP, in seconds.
LEEWAY_SECONDS = 30
DISCOVERY_PATH = "/.well-known/openid-configuration"
HTTP_TIMEOUT = 5.0


class AuthConfigurationError(RuntimeError):
    """OIDC mode is requested but the configuration cannot support it."""


class TokenError(Exception):
    """The presented token is absent, malformed, expired or not ours."""


@dataclass(frozen=True)
class Identity:
    """A verified caller. Only claims that were actually checked appear here."""

    subject: str
    name: str = ""
    email: str = ""
    roles: tuple[str, ...] = ()

    @property
    def is_staff(self) -> bool:
        """Whether the token grants Challenge Studio access.

        Role names are NxtWave's to define, so the set to accept is
        configuration (`BREAKPOINT_OIDC_STAFF_ROLES`). With none configured no
        token confers staff rights, and the Studio keeps using its own token -
        failing closed rather than inventing a role name.
        """
        allowed = {r.strip() for r in settings.oidc_staff_roles if r.strip()}
        return bool(allowed and allowed.intersection(self.roles))


def missing_configuration() -> list[str]:
    """The settings OIDC mode needs and does not have.

    Returned rather than raised so `/api/health` and the auth check script can
    report the gap without the app refusing to start in header mode.
    """
    required = {
        "BREAKPOINT_OIDC_ISSUER": settings.oidc_issuer,
        "BREAKPOINT_OIDC_AUDIENCE": settings.oidc_audience,
        "BREAKPOINT_OIDC_SUBJECT_CLAIM": settings.oidc_subject_claim,
    }
    return [name for name, value in required.items() if not str(value).strip()]


def is_configured() -> bool:
    return not missing_configuration()


def is_enabled() -> bool:
    """Whether requests should be verified as OIDC bearer tokens."""
    return settings.auth_mode.lower() == "oidc"


# --- Provider metadata and keys --------------------------------------------


class _Cache:
    """Discovery document and JWKS, refetched on TTL or on an unknown key id.

    Guarded by a lock: several requests arriving on a cold cache should cause
    one fetch, not one per request.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at = 0.0

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            if self._metadata is None:
                url = settings.oidc_issuer.rstrip("/") + DISCOVERY_PATH
                self._metadata = _get_json(url, "discovery document")
            return self._metadata

    def jwks(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            fresh = (
                self._jwks is not None
                and time.monotonic() - self._jwks_fetched_at < JWKS_TTL_SECONDS
            )
            if fresh and not force:
                return self._jwks  # type: ignore[return-value]
        # Fetch outside the lock: a slow IdP must not block every caller.
        url = settings.oidc_jwks_url or self.metadata().get("jwks_uri", "")
        if not url:
            raise AuthConfigurationError(
                "the discovery document has no jwks_uri and "
                "BREAKPOINT_OIDC_JWKS_URL is unset"
            )
        keys = _get_json(url, "JWKS")
        with self._lock:
            self._jwks = keys
            self._jwks_fetched_at = time.monotonic()
        return keys

    def reset(self) -> None:
        with self._lock:
            self._metadata = None
            self._jwks = None
            self._jwks_fetched_at = 0.0


_cache = _Cache()


def _get_json(url: str, what: str) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise TokenError(f"could not fetch the {what} from {url}: {exc}") from exc


# --- Verification -----------------------------------------------------------


def bearer_token(authorization: str) -> str:
    """Extract the token from an Authorization header."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise TokenError("expected an 'Authorization: Bearer <token>' header")
    return token.strip()


def verify(token: str) -> Identity:
    """Verify a bearer token and return the identity it asserts.

    Raises TokenError for anything unverifiable. There is deliberately no
    partial success: a token whose signature checks out but whose audience does
    not is rejected, because it was issued for a different service.
    """
    if not is_configured():
        raise AuthConfigurationError(
            "OIDC verification requires " + ", ".join(missing_configuration())
        )

    import jwt  # noqa: PLC0415 - optional dependency, only needed in OIDC mode
    from jwt import PyJWKClient  # noqa: PLC0415

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TokenError(f"malformed token: {exc}") from exc

    algorithm = header.get("alg", "")
    if algorithm not in settings.oidc_algorithms:
        # An attacker's first move is to change `alg`, so the allowlist is
        # checked against configuration rather than read from the token.
        raise TokenError(f"unsupported token algorithm {algorithm!r}")

    jwks_url = settings.oidc_jwks_url or _cache.metadata().get("jwks_uri", "")
    try:
        signing_key = PyJWKClient(jwks_url, cache_keys=True).get_signing_key_from_jwt(
            token
        )
    except Exception as exc:  # noqa: BLE001 - PyJWK raises several unrelated types
        raise TokenError(f"no signing key matched the token: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(settings.oidc_algorithms),
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("the token has expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenError("the token was issued for a different audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenError("the token was issued by an unexpected issuer") from exc
    except jwt.PyJWTError as exc:
        raise TokenError(f"token verification failed: {exc}") from exc

    return identity_from_claims(claims)


def identity_from_claims(claims: dict[str, Any]) -> Identity:
    """Map verified claims onto an Identity using the configured claim names.

    Separated from `verify` so the claim contract can be tested against a
    sample token payload without a live identity provider - which is the only
    part of this that can be exercised before credentials exist.
    """
    subject = str(claims.get(settings.oidc_subject_claim, "")).strip()
    if not subject:
        raise TokenError(
            f"the token has no {settings.oidc_subject_claim!r} claim, so the "
            "student cannot be identified"
        )

    roles_claim = claims.get(settings.oidc_roles_claim)
    if isinstance(roles_claim, str):
        roles = tuple(r.strip() for r in roles_claim.split() if r.strip())
    elif isinstance(roles_claim, (list, tuple)):
        roles = tuple(str(r).strip() for r in roles_claim if str(r).strip())
    else:
        roles = ()

    return Identity(
        subject=subject,
        name=str(claims.get(settings.oidc_name_claim, "") or "").strip(),
        email=str(claims.get(settings.oidc_email_claim, "") or "").strip(),
        roles=roles,
    )


def status() -> dict[str, Any]:
    """What `/api/health` and the auth check script report."""
    missing = missing_configuration()
    return {
        "mode": settings.auth_mode.lower(),
        "oidc_enabled": is_enabled(),
        "oidc_configured": not missing,
        "missing_settings": missing,
        "issuer": settings.oidc_issuer or None,
        "subject_claim": settings.oidc_subject_claim or None,
        "staff_roles_configured": bool(
            [r for r in settings.oidc_staff_roles if r.strip()]
        ),
    }
