"""Application settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_prefix="BREAKPOINT_", extra="ignore"
    )

    database_url: str = f"sqlite:///{BASE_DIR / 'breakpoint.db'}"
    content_dir: Path = BASE_DIR / "content"

    # --- AI Gateway (PRD section 73) --------------------------------------
    # Model choice is config, not code, so the product survives model changes
    # and is not tied to one vendor.
    #
    # "auto" picks the first configured provider: openrouter, then anthropic.
    ai_provider: str = "auto"

    # Anthropic (native Messages API). Preferred when available - it supports
    # adaptive thinking, prompt-cache breakpoints and refusal fallbacks.
    anthropic_api_key: str = ""
    generation_model: str = "claude-opus-5"
    critic_model: str = "claude-opus-5"
    debate_model: str = "claude-opus-5"
    evidence_model: str = "claude-opus-5"

    # OpenRouter (OpenAI-compatible gateway to many vendors).
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:5173"
    openrouter_app_name: str = "NxtWave Breakpoint"
    # Generation and critique carry the quality bar, so they default to the
    # strongest model; debate and evidence run far more often per session and
    # are well served by a cheaper one.
    openrouter_generation_model: str = "anthropic/claude-opus-5"
    openrouter_critic_model: str = "anthropic/claude-opus-5"
    openrouter_debate_model: str = "anthropic/claude-sonnet-5"
    openrouter_evidence_model: str = "anthropic/claude-sonnet-5"

    # PRD section 76 - challenges below this mean quality score never publish.
    quality_threshold: float = 7.0
    # PRD section 46.5 - reject if the critic finds the challenge too ambiguous.
    max_ambiguity: float = 0.35
    # PRD v0.2 section 3.2 truth mix across launch inventory:
    # 78 flawed, 30 valid, 6 insufficient-information of 114.
    valid_artifact_ratio: float = 30 / 114
    insufficient_information_ratio: float = 6 / 114
    # PRD v0.2 section 9.3 - default maximum 3 AI defense replies per attempt.
    max_debate_turns: int = 3

    # Challenge Studio access. Development default is permissive so the Studio
    # is usable out of the box; set BREAKPOINT_ADMIN_TOKEN in any shared or
    # deployed environment and the header becomes mandatory.
    admin_token: str = ""
    # Cap on candidates per generation job - each costs four model calls.
    max_generation_batch: int = 10

    # --- Identity (PRD sections 105, 12.5) --------------------------------
    # "header" trusts X-Student-Id, which is right for local development and
    # for the demo. "oidc" verifies a bearer token against NxtWave's identity
    # provider. Switching to oidc without the three required values below
    # fails closed: every request is rejected rather than silently falling
    # back, because a fallback that looks like SSO is worse than an outage.
    # "accounts" is the third mode: Breakpoint owns identity itself, with
    # email/password sign-up and Google sign-in, and a session cookie. It
    # fails closed too - with accounts on, X-Student-Id buys nothing.
    auth_mode: str = "header"

    # --- Accounts mode ----------------------------------------------------
    session_cookie_name: str = "bp_session"
    session_ttl_days: int = 30
    # Off by default because local development is plain http, where a Secure
    # cookie is silently dropped. Turn it on wherever the site is https.
    session_cookie_secure: bool = False
    # Failed sign-ins per address before that address is paused briefly. Per
    # process, so it slows an attacker rather than stopping a distributed one.
    login_attempt_limit: int = 8
    login_attempt_window_seconds: int = 300

    # Google sign-in. Created in a Google Cloud project; the button stays
    # hidden until both values are present, the same fail-visible rule the
    # SSO adapter follows. The secret belongs in backend/.env, never in code.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must match a redirect URI registered on that Google client exactly. The
    # default is the dev server, which proxies /api to this backend.
    google_redirect_uri: str = "http://localhost:5173/api/auth/google/callback"
    # Where the browser lands after a completed sign-in.
    google_post_login_path: str = "/"

    oidc_issuer: str = ""
    oidc_audience: str = ""
    # Which claim carries the durable student id. There is no safe default:
    # providers use `sub`, `preferred_username` or a tenant-specific claim,
    # and guessing wrong merges or duplicates accounts.
    oidc_subject_claim: str = ""
    oidc_name_claim: str = "name"
    oidc_email_claim: str = "email"
    oidc_roles_claim: str = "roles"
    # Roles that grant Challenge Studio access. Empty means no token confers
    # staff rights and the Studio keeps using its own admin token.
    oidc_staff_roles: list[str] = []
    # Signature algorithms accepted. Asymmetric only - an HMAC algorithm here
    # would let anyone holding the client secret mint student tokens.
    oidc_algorithms: list[str] = ["RS256", "RS512", "ES256"]
    # Optional override when the provider's discovery document is unreachable
    # but its key set is published directly.
    oidc_jwks_url: str = ""

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


settings = Settings()
