"""Accounts mode: Breakpoint owns identity.

Email and password, or Google (app/auth/google.py), resolving to the same
`User` rows every other mode produces - so nothing downstream knows or cares
how a student signed in.

Session tokens are opaque random strings, stored only as a SHA-256 hash and
carried in an httpOnly cookie. Opaque rather than a JWT because sign-out must
actually revoke: a self-contained token stays valid until it expires, and
"log out everywhere" then becomes a lie.

Two rules worth stating, because both are easy to get wrong and neither is
visible in a passing test:

  * **No account enumeration.** Wrong address and wrong password give the
    same message and take a comparable time, so this endpoint cannot be used
    to discover who has an account.
  * **Sign-up is not sign-in evidence.** Creating an account issues a fresh
    session like any other sign-in; it never trusts a client-supplied id.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import passwords
from app.config import settings
from app.models import LoginSession, User

TOKEN_BYTES = 32
EMAIL_PREFIX = "email:"
GOOGLE_PREFIX = "google:"


class AuthError(Exception):
    """Sign-in or sign-up refused. The message is safe to show a student."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def is_enabled() -> bool:
    return settings.auth_mode == "accounts"


# --- password sign-up and sign-in --------------------------------------------


def create_account(session: Session, *, email: str, password: str, name: str) -> User:
    """Register an email account. Raises AuthError if it cannot be created."""
    try:
        address = passwords.check_email(email)
        passwords.check_policy(password, email=address, name=name)
    except passwords.PasswordRejected as exc:
        raise AuthError(str(exc)) from exc

    display = name.strip()[:200]
    if not display:
        raise AuthError("Tell us what to call you.")

    existing = session.scalar(select(User).where(User.login_email == address))
    if existing is not None:
        # Deliberately explicit: this one *is* an enumeration signal, and
        # hiding it would leave a student who forgot they had signed up
        # unable to explain why their sign-up "worked" but nothing happened.
        raise AuthError("An account already exists for that address. Sign in instead.", status=409)

    user = session.scalar(select(User).where(User.external_id == EMAIL_PREFIX + address))
    if user is None:
        user = User(external_id=EMAIL_PREFIX + address)
        session.add(user)
    user.login_email = address
    user.email = address
    user.name = display
    user.password_hash = passwords.hash_password(password)
    session.flush()
    return user


def authenticate(session: Session, *, email: str, password: str) -> User:
    """Check an email and password. Raises AuthError on any failure."""
    address = passwords.normalise_email(email)
    _check_not_throttled(address)

    user = session.scalar(select(User).where(User.login_email == address))
    stored = user.password_hash if user and user.password_hash else ""
    # Hash even when there is no account, so a missing address and a wrong
    # password cost the same time and cannot be told apart.
    ok = passwords.verify_password(password, stored or _DUMMY_HASH)
    if user is None or not user.password_hash or not ok:
        _record_failure(address)
        raise AuthError("That email or password is not right.", status=401)

    _clear_failures(address)
    if passwords.needs_rehash(user.password_hash):
        # Cheap to do here: the plaintext is in hand exactly once per login.
        user.password_hash = passwords.hash_password(password)
    return user


# A real hash of a random string, so the no-account path does the same work
# as the wrong-password path instead of returning early.
_DUMMY_HASH = passwords.hash_password(secrets.token_urlsafe(16))


# --- Google accounts ---------------------------------------------------------


@dataclass(frozen=True)
class GoogleProfile:
    subject: str
    email: str
    name: str
    email_verified: bool


def upsert_google_account(session: Session, profile: GoogleProfile) -> User:
    """Find or create the student behind a verified Google profile.

    Linking rule: a Google sign-in claiming an address that already has a
    password account joins that account rather than creating a second one -
    but only when Google says the address is verified, or an attacker could
    claim someone else's address on their own Google tenant.
    """
    address = passwords.normalise_email(profile.email)
    user = session.scalar(select(User).where(User.google_sub == profile.subject))
    if user is None and address and profile.email_verified:
        user = session.scalar(select(User).where(User.login_email == address))
    if user is None:
        user = session.scalar(
            select(User).where(User.external_id == GOOGLE_PREFIX + profile.subject)
        )
    if user is None:
        user = User(external_id=GOOGLE_PREFIX + profile.subject)
        session.add(user)

    user.google_sub = profile.subject
    if address:
        user.email = address
        if user.login_email is None and profile.email_verified:
            user.login_email = address
    if profile.name and not user.name:
        user.name = profile.name[:200]
    session.flush()
    return user


# --- sessions ----------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(session: Session, user: User, *, user_agent: str = "") -> str:
    """Issue a session and return the cookie value. Stored hashed."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = datetime.now(UTC)
    session.add(
        LoginSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            created_at=now,
            expires_at=now + timedelta(days=settings.session_ttl_days),
            user_agent=user_agent[:200],
        )
    )
    user.last_login_at = now
    return token


def user_for_token(session: Session, token: str) -> User | None:
    """The signed-in student, or None when the cookie is unusable."""
    if not token:
        return None
    record = session.scalar(
        select(LoginSession).where(LoginSession.token_hash == _hash_token(token))
    )
    if record is None or record.revoked_at is not None:
        return None
    if _aware(record.expires_at) <= datetime.now(UTC):
        return None
    return session.get(User, record.user_id)


def end_session(session: Session, token: str) -> bool:
    """Revoke one session. True when a live session was ended."""
    record = session.scalar(
        select(LoginSession).where(LoginSession.token_hash == _hash_token(token))
    )
    if record is None or record.revoked_at is not None:
        return False
    record.revoked_at = datetime.now(UTC)
    return True


def _aware(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; stored values are UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# --- login throttling --------------------------------------------------------
#
# Per process and in memory: it slows down guessing against one address on one
# server. It is not a defence against a distributed attack, and it is not
# claimed to be - that belongs at the edge.

_failures: dict[str, list[float]] = {}


def _recent(address: str) -> list[float]:
    window = settings.login_attempt_window_seconds
    now = time.monotonic()
    kept = [t for t in _failures.get(address, []) if now - t < window]
    if kept:
        _failures[address] = kept
    else:
        _failures.pop(address, None)
    return kept


def _check_not_throttled(address: str) -> None:
    if len(_recent(address)) >= settings.login_attempt_limit:
        raise AuthError(
            "Too many sign-in attempts for that address. Wait a few minutes "
            "and try again.",
            status=429,
        )


def _record_failure(address: str) -> None:
    _failures.setdefault(address, []).append(time.monotonic())


def _clear_failures(address: str) -> None:
    _failures.pop(address, None)


def reset_throttle() -> None:
    """Clear the failure record. For tests and for a deliberate unlock."""
    _failures.clear()
