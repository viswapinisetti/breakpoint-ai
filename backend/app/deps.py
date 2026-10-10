"""Shared request dependencies.

Authentication is an *adapter* (PRD section 105): Breakpoint does not own
identity, it consumes it. Two modes, selected by `BREAKPOINT_AUTH_MODE`:

* `header` (default) - the NxtWave session is represented by an `X-Student-Id`
  header. Right for local development and the demo.
* `oidc` - the caller presents a bearer token, verified against NxtWave's
  identity provider by `app.auth.oidc`.
* `accounts` - Breakpoint owns identity: email/password or Google sign-in,
  carried in a session cookie by `app.auth.accounts`.

All three resolve to the same `Identity`, so no router knows which is in use.
Both non-header modes fail closed: if OIDC is enabled and misconfigured, or
accounts mode gets no valid session, the request is rejected rather than
falling back to the header - an identity system that silently accepts an
unverified header is worse than one that is visibly down.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import accounts, oidc
from app.config import settings
from app.db import get_session
from app.engine.contracts import Challenge
from app.models import ChallengeRecord, User

SessionDep = Annotated[Session, Depends(get_session)]


def resolve_identity(
    authorization: str = "",
    x_student_id: str = "",
    x_student_name: str = "",
) -> oidc.Identity:
    """Turn the request's credentials into a verified identity.

    Kept free of FastAPI types so it can be exercised directly by the auth
    check script without constructing a request.
    """
    if oidc.is_enabled():
        missing = oidc.missing_configuration()
        if missing:
            # Deliberately a 503, not a 401: nothing is wrong with the
            # caller's credentials, the server cannot verify anything.
            raise HTTPException(
                status_code=503,
                detail=(
                    "SSO is enabled but not configured; missing "
                    + ", ".join(missing)
                ),
            )
        try:
            return oidc.verify(oidc.bearer_token(authorization))
        except oidc.TokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except oidc.AuthConfigurationError as exc:  # pragma: no cover
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    student_id = (x_student_id or "demo-student").strip()
    if not student_id:
        raise HTTPException(status_code=401, detail="missing student identity")
    return oidc.Identity(subject=student_id, name=x_student_name.strip())


def _session_cookie(request_cookie: str | None) -> str:
    return (request_cookie or "").strip()


def current_user_optional(
    session: SessionDep,
    bp_session: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
    authorization: Annotated[str, Header()] = "",
    x_student_id: Annotated[str, Header()] = "",
    x_student_name: Annotated[str, Header()] = "",
) -> User | None:
    """The caller, or None when nobody is signed in.

    Used by `/api/auth/me`, which a signed-out visitor must be able to call
    without it reading as an error.
    """
    if accounts.is_enabled():
        return accounts.user_for_token(session, _session_cookie(bp_session))
    try:
        return current_user(
            session, bp_session, authorization, x_student_id or "demo-student", x_student_name
        )
    except HTTPException:
        return None


def current_user(
    session: SessionDep,
    bp_session: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
    authorization: Annotated[str, Header()] = "",
    x_student_id: Annotated[str, Header()] = "demo-student",
    x_student_name: Annotated[str, Header()] = "",
) -> User:
    """Resolve (or provision) the calling student."""
    if accounts.is_enabled():
        # Accounts mode owns identity: the cookie is the only credential, and
        # X-Student-Id buys nothing. Anything else would make every account a
        # formality.
        user = accounts.user_for_token(session, _session_cookie(bp_session))
        if user is None:
            raise HTTPException(status_code=401, detail="sign in to continue")
        return user

    identity = resolve_identity(authorization, x_student_id, x_student_name)
    user = session.scalar(select(User).where(User.external_id == identity.subject))
    if user is None:
        user = User(
            external_id=identity.subject,
            name=identity.name or identity.subject.replace("-", " ").title(),
            email=identity.email,
        )
        session.add(user)
        session.commit()
        return user
    # Keep the profile in step with the identity provider, which owns these
    # fields. Nothing else about the user record is overwritten.
    if identity.name and user.name != identity.name:
        user.name = identity.name
    if identity.email and user.email != identity.email:
        user.email = identity.email
    return user


UserDep = Annotated[User, Depends(current_user)]


def touch_streak(user: User) -> None:
    """Advance the verification streak (PRD section 36.5).

    Counts a day on which the student investigated at least one challenge.
    Consecutive days extend the streak; a gap resets it to 1.
    """
    today = datetime.now(UTC).date()
    today_str = today.isoformat()
    if user.streak_last_day == today_str:
        return
    yesterday = (today - timedelta(days=1)).isoformat()
    user.streak_days = user.streak_days + 1 if user.streak_last_day == yesterday else 1
    user.streak_last_day = today_str


def current_staff(
    authorization: Annotated[str, Header()] = "",
    x_admin_token: Annotated[str, Header()] = "",
    x_staff_name: Annotated[str, Header()] = "",
) -> str:
    """Authorise a Challenge Studio caller and return their display name.

    Two independent grants, and either suffices:

    * a staff role in a verified SSO token, when `oidc_staff_roles` names one;
    * the `X-Admin-Token` shared secret.

    When neither `admin_token` nor a staff role is configured the Studio is
    open, which keeps local development frictionless. Configuring either makes
    authorisation mandatory - it fails closed the moment a credential exists.
    """
    roles_configured = any(r.strip() for r in settings.oidc_staff_roles)
    if oidc.is_enabled() and oidc.is_configured():
        try:
            identity = oidc.verify(oidc.bearer_token(authorization))
        except (oidc.TokenError, oidc.AuthConfigurationError):
            identity = None
        if identity is not None and identity.is_staff:
            return identity.name or identity.subject

    if settings.admin_token and x_admin_token == settings.admin_token:
        return x_staff_name or "content-developer"

    if settings.admin_token or roles_configured:
        raise HTTPException(status_code=403, detail="Challenge Studio access denied")
    return x_staff_name or "content-developer"


StaffDep = Annotated[str, Depends(current_staff)]


def load_challenge(record: ChallengeRecord) -> Challenge:
    """Rehydrate the validated challenge object from its stored body."""
    return Challenge.model_validate(record.body)


def get_record(session: Session, challenge_id: str) -> ChallengeRecord:
    record = session.scalar(
        select(ChallengeRecord).where(ChallengeRecord.challenge_id == challenge_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown challenge {challenge_id}")
    return record
