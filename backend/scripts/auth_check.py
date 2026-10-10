"""Report the identity configuration, and test what can be tested without it.

    python -m scripts.auth_check

PRD v0.2 section 12.5 is explicit that a working SSO integration must not be
claimed without credentials and an API contract. This script is how that
honesty is enforced in practice: it says which mode is live, which settings are
missing, and - crucially - exercises the parts of the OIDC path that do not
need a live identity provider, so the claim-mapping contract is verified rather
than asserted.

When NxtWave supplies the three required values, run this again: it moves from
"header mode" to a live check against the real discovery document and JWKS.
"""

from __future__ import annotations

import sys

from app.auth import oidc
from app.config import settings
from app.deps import resolve_identity

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label} {detail}")


def main() -> int:
    status = oidc.status()

    print("\n[identity configuration]")
    print(f"       auth mode          {status['mode']}")
    print(f"       oidc enabled       {status['oidc_enabled']}")
    print(f"       oidc configured    {status['oidc_configured']}")
    print(f"       issuer             {status['issuer'] or '(unset)'}")
    print(f"       subject claim      {status['subject_claim'] or '(unset)'}")
    print(f"       staff roles set    {status['staff_roles_configured']}")

    if status["missing_settings"]:
        print("\n       SSO is NOT active. Missing configuration:")
        for name in status["missing_settings"]:
            print(f"         - {name}")
        print(
            "\n       These come from NxtWave's identity provider and cannot be\n"
            "       inferred. Supply them plus BREAKPOINT_AUTH_MODE=oidc and\n"
            "       re-run this script for a live verification check."
        )

    print("\n[header mode]")
    identity = resolve_identity(x_student_id="student-42", x_student_name="Asha")
    check("header identity resolves", identity.subject == "student-42")
    check("display name carried through", identity.name == "Asha")
    check("no roles are granted by a header", identity.roles == ())
    check("a header never confers staff rights", identity.is_staff is False)

    print("\n[claim mapping contract]")
    # The only part of the OIDC path testable without an identity provider,
    # and the part most likely to be wrong when one arrives: which claim is
    # read for what.
    original_subject = settings.oidc_subject_claim
    original_roles = list(settings.oidc_staff_roles)
    try:
        settings.oidc_subject_claim = "student_id"
        settings.oidc_staff_roles = ["breakpoint-content-dev"]
        mapped = oidc.identity_from_claims(
            {
                "sub": "auth0|abc123",
                "student_id": "NW-98213",
                "name": "Ravi Kumar",
                "email": "ravi@example.edu",
                "roles": ["learner", "breakpoint-content-dev"],
            }
        )
        check("subject read from the configured claim, not `sub`",
              mapped.subject == "NW-98213", mapped.subject)
        check("name mapped", mapped.name == "Ravi Kumar")
        check("email mapped", mapped.email == "ravi@example.edu")
        check("roles mapped as a tuple",
              mapped.roles == ("learner", "breakpoint-content-dev"))
        check("configured staff role recognised", mapped.is_staff is True)

        settings.oidc_staff_roles = []
        check("no staff role configured means no staff access",
              oidc.identity_from_claims(
                  {"student_id": "NW-1", "roles": ["admin"]}
              ).is_staff is False)

        # Space-delimited roles are as common as arrays in real tokens.
        settings.oidc_staff_roles = ["content-dev"]
        spaced = oidc.identity_from_claims(
            {"student_id": "NW-2", "roles": "learner content-dev"}
        )
        check("space-delimited roles parsed",
              spaced.roles == ("learner", "content-dev"))

        try:
            oidc.identity_from_claims({"sub": "auth0|abc123", "name": "No Id"})
        except oidc.TokenError as exc:
            check("a token missing the subject claim is rejected",
                  "student_id" in str(exc), str(exc))
        else:
            check("a token missing the subject claim is rejected", False,
                  "it was accepted")
    finally:
        settings.oidc_subject_claim = original_subject
        settings.oidc_staff_roles = original_roles

    print("\n[fail-closed behaviour]")
    original_mode = settings.auth_mode
    original_issuer = settings.oidc_issuer
    try:
        settings.auth_mode = "oidc"
        settings.oidc_issuer = ""
        try:
            resolve_identity(x_student_id="student-42")
        except Exception as exc:  # noqa: BLE001 - HTTPException is what we want
            code = getattr(exc, "status_code", None)
            check("enabling SSO without configuration rejects requests",
                  code == 503, f"status {code}")
            check("it does not fall back to the header",
                  "student-42" not in str(getattr(exc, "detail", "")))
        else:
            check("enabling SSO without configuration rejects requests", False,
                  "the header was accepted")
    finally:
        settings.auth_mode = original_mode
        settings.oidc_issuer = original_issuer

    if oidc.is_configured():
        print("\n[live provider check]")
        try:
            metadata = oidc._cache.metadata()  # noqa: SLF001 - diagnostic script
            check("discovery document fetched", "jwks_uri" in metadata,
                  str(sorted(metadata)[:6]))
            keys = oidc._cache.jwks()  # noqa: SLF001
            check("JWKS fetched with at least one key",
                  bool(keys.get("keys")), str(keys)[:120])
        except Exception as exc:  # noqa: BLE001
            check("provider metadata reachable", False, str(exc))
    else:
        print("\n[live provider check]")
        print("       skipped - no issuer configured (see above)")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all identity checks passed")
    if not oidc.is_configured():
        print(
            "NOTE: SSO itself is unverified because no identity provider is "
            "configured.\n      What is verified: the claim-mapping contract "
            "and the fail-closed guard."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
