"""Sign-up, sign-in and sign-out for accounts mode.

These endpoints exist in every mode so the client can ask what is available
(`GET /api/auth/providers`) and get a straight answer, but they only issue
sessions when `BREAKPOINT_AUTH_MODE=accounts`. In header or SSO mode, signing
in here would create a second, contradictory notion of who the caller is.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth import accounts, google
from app.auth import oidc
from app.config import settings
from app.deps import SessionDep, current_user_optional
from app.models import AnalyticsEvent, User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"], prefix="/auth")


class SignUpRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    name: str = Field(max_length=200)


class SignInRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class Profile(BaseModel):
    """Who the caller is, as the client should display them."""

    signed_in: bool
    name: str = ""
    email: str = ""
    #: password | google | header | oidc - how this session was established.
    provider: str = ""
    external_id: str = ""


class Providers(BaseModel):
    mode: str
    password: bool
    google: bool
    #: Why Google is unavailable, when it is.
    google_unavailable: str = ""
    #: True when the app should require sign-in before showing anything.
    sign_in_required: bool


def _require_accounts_mode() -> None:
    if not accounts.is_enabled():
        raise HTTPException(
            status_code=409,
            detail=(
                f"This server runs in {settings.auth_mode} mode, so it does not "
                "manage passwords. Set BREAKPOINT_AUTH_MODE=accounts to use "
                "accounts."
            ),
        )


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        # Lax, not None: the cookie rides top-level navigations (the Google
        # redirect lands as one) but not cross-site form posts, which is the
        # CSRF case that matters for these endpoints.
        samesite="lax",
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")


def _profile(user: User, provider: str) -> Profile:
    return Profile(
        signed_in=True,
        name=user.name,
        email=user.email,
        provider=provider,
        external_id=user.external_id,
    )


def _provider_of(user: User) -> str:
    if settings.auth_mode != "accounts":
        return settings.auth_mode
    return "google" if user.google_sub and not user.password_hash else "password"


def _log(session, user_id: int | None, name: str, **payload) -> None:
    session.add(AnalyticsEvent(user_id=user_id, name=name, payload=payload))


@router.get("/providers", response_model=Providers)
def providers() -> Providers:
    """What sign-in this server offers. The client renders exactly this."""
    google_status = google.status()
    unavailable = ""
    if accounts.is_enabled() and not google_status["configured"]:
        unavailable = (
            "Google sign-in is not configured on this server: missing "
            + ", ".join(google_status["missing_settings"])
        )
    return Providers(
        mode=settings.auth_mode,
        password=accounts.is_enabled(),
        google=accounts.is_enabled() and bool(google_status["configured"]),
        google_unavailable=unavailable,
        sign_in_required=accounts.is_enabled(),
    )


@router.get("/me", response_model=Profile)
def me(user: User | None = Depends(current_user_optional)) -> Profile:
    """The signed-in student, or `signed_in: false`. Never 401s, so the app
    can ask on load without treating a signed-out visitor as an error."""
    if user is None:
        return Profile(signed_in=False)
    return _profile(user, _provider_of(user))


@router.post("/signup", response_model=Profile, status_code=201)
def sign_up(
    body: SignUpRequest, request: Request, response: Response, session: SessionDep
) -> Profile:
    _require_accounts_mode()
    try:
        user = accounts.create_account(
            session, email=body.email, password=body.password, name=body.name
        )
    except accounts.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    token = accounts.start_session(
        session, user, user_agent=request.headers.get("user-agent", "")
    )
    _log(session, user.id, "account_created", provider="password")
    session.commit()
    _set_cookie(response, token)
    return _profile(user, "password")


@router.post("/login", response_model=Profile)
def sign_in(
    body: SignInRequest, request: Request, response: Response, session: SessionDep
) -> Profile:
    _require_accounts_mode()
    try:
        user = accounts.authenticate(session, email=body.email, password=body.password)
    except accounts.AuthError as exc:
        session.commit()  # keep any rehash or throttle bookkeeping
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    token = accounts.start_session(
        session, user, user_agent=request.headers.get("user-agent", "")
    )
    _log(session, user.id, "signed_in", provider="password")
    session.commit()
    _set_cookie(response, token)
    return _profile(user, "password")


@router.post("/logout", status_code=204)
def sign_out(
    response: Response,
    session: SessionDep,
    bp_session: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> Response:
    """Revoke this session. Idempotent: signing out twice is not an error."""
    if bp_session:
        accounts.end_session(session, bp_session)
        session.commit()
    _clear_cookie(response)
    response.status_code = 204
    return response


# --- Google ------------------------------------------------------------------


@router.get("/google/start")
def google_start(session: SessionDep) -> RedirectResponse:
    """Send the browser to Google. Refuses plainly when unconfigured."""
    _require_accounts_mode()
    try:
        url, _handshake = google.begin(session)
    except google.GoogleError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    session.commit()
    return RedirectResponse(url, status_code=302)


@router.get("/google/callback")
def google_callback(
    session: SessionDep,
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    """Where Google sends the browser back.

    Ends in a redirect either way, because this URL is opened by the browser
    itself: a JSON error here would strand the student on a blank page. The
    reason travels as a query parameter for the sign-in screen to show.
    """
    _require_accounts_mode()
    if error:
        return _google_failure(f"Google reported: {error}")
    if not state or not code:
        return _google_failure("Google's reply was incomplete. Try again.")
    try:
        handshake = google.take_handshake(session, state)
        tokens = google.exchange_code(code, handshake.code_verifier)
        id_token = tokens.get("id_token") or ""
        if not id_token:
            raise google.GoogleError("Google did not return an ID token.")
        profile = google.profile_from_id_token(id_token, nonce=handshake.nonce)
        user = accounts.upsert_google_account(session, profile)
        token = accounts.start_session(
            session, user, user_agent=request.headers.get("user-agent", "")
        )
        _log(session, user.id, "signed_in", provider="google")
        session.commit()
    except google.GoogleError as exc:
        session.commit()  # the handshake stays consumed
        logger.info("google sign-in failed: %s", exc)
        return _google_failure(str(exc))

    response = RedirectResponse(settings.google_post_login_path, status_code=302)
    _set_cookie(response, token)
    return response


def _google_failure(reason: str) -> RedirectResponse:
    from urllib.parse import quote

    return RedirectResponse(
        f"{settings.google_post_login_path}?auth_error={quote(reason)}", status_code=302
    )


@router.get("/status")
def auth_status() -> dict:
    """Diagnostics for an operator: which mode, and what is missing."""
    return {
        "mode": settings.auth_mode,
        "accounts": accounts.is_enabled(),
        "google": google.status(),
        "oidc": oidc.status(),
        "session_cookie": settings.session_cookie_name,
        "session_cookie_secure": settings.session_cookie_secure,
    }
