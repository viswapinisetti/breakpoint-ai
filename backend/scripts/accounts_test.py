"""Accounts mode: email/password sign-up and sign-in, sessions, Google.

Runs entirely offline. The Google leg never contacts Google: the token
exchange is replaced with a stub that returns an ID token this test builds, so
every claim check - issuer, audience, nonce, expiry - is exercised against
tokens that are deliberately right and deliberately wrong.

    python -m scripts.accounts_test
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from scripts.testdb import use_temp_database

use_temp_database()
# Must precede the app import: settings are read once, at import time.
os.environ["BREAKPOINT_AUTH_MODE"] = "accounts"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import accounts, google, passwords  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

failures: list[str] = []
EMAIL = "asha@example.com"
PASSWORD = "kettle harbour lantern"
NAME = "Asha Rao"


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}  {detail}")


def id_token(**claims) -> str:
    """A Google-shaped ID token. Only the payload is read (see google.py)."""
    payload = {
        "iss": "https://accounts.google.com",
        "aud": settings.google_client_id,
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "sub": "google-sub-1",
        "email": "asha@gmail.com",
        "email_verified": True,
        "name": "Asha From Google",
        **claims,
    }
    part = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{part}.signature"


def main() -> int:  # noqa: PLR0915 - a linear script reads better here
    with TestClient(app) as client:
        print("\n[what this server offers]")
        p = client.get("/api/auth/providers").json()
        check("accounts mode reported", p["mode"] == "accounts" and p["password"], p)
        check("sign-in is required", p["sign_in_required"] is True, p)
        check("Google is off until configured", p["google"] is False, p)
        check(
            "and says which settings are missing",
            "BREAKPOINT_GOOGLE_CLIENT_ID" in p["google_unavailable"],
            p["google_unavailable"],
        )

        print("\n[nothing is readable while signed out]")
        check("me reports signed out", client.get("/api/auth/me").json()["signed_in"] is False)
        check("stats refused", client.get("/api/stats").status_code == 401)
        spoof = client.get("/api/stats", headers={"X-Student-Id": "someone"})
        check("X-Student-Id buys nothing in accounts mode", spoof.status_code == 401,
              spoof.status_code)

        print("\n[sign-up refuses what it should]")
        for label, body, expect in (
            ("a malformed address", {"email": "not-an-email", "password": PASSWORD, "name": NAME}, "email address"),
            ("a short password", {"email": EMAIL, "password": "short1", "name": NAME}, "at least 10"),
            ("a famous password", {"email": EMAIL, "password": "password123", "name": NAME}, "attackers try first"),
            ("a password built from the address", {"email": EMAIL, "password": "asha-asha-asha", "name": NAME}, "your own name"),
            ("no name", {"email": EMAIL, "password": PASSWORD, "name": "  "}, "what to call you"),
        ):
            r = client.post("/api/auth/signup", json=body)
            check(f"{label} is refused", r.status_code == 400, r.status_code)
            check(f"...and explains why ({label})", expect in r.json()["detail"], r.json())

        print("\n[sign-up]")
        r = client.post(
            "/api/auth/signup", json={"email": "  Asha@Example.com ", "password": PASSWORD, "name": NAME}
        )
        check("account created", r.status_code == 201, r.text[:200])
        body = r.json()
        check("the profile comes back", body["signed_in"] and body["name"] == NAME, body)
        check("the address is normalised", body["email"] == EMAIL, body["email"])
        cookie = client.cookies.get(settings.session_cookie_name)
        check("a session cookie is set", bool(cookie))
        set_cookie = r.headers.get("set-cookie", "")
        check("the cookie is httpOnly", "httponly" in set_cookie.lower(), set_cookie)
        check("and SameSite=Lax", "samesite=lax" in set_cookie.lower(), set_cookie)

        print("\n[the session is the credential]")
        check("me is signed in", client.get("/api/auth/me").json()["signed_in"] is True)
        check("stats readable", client.get("/api/stats").status_code == 200)
        started = client.post("/api/challenges/apt-pct-001/start")
        check("an investigation can be started", started.status_code == 200, started.status_code)

        print("\n[a second account cannot take the same address]")
        again = client.post(
            "/api/auth/signup", json={"email": EMAIL, "password": PASSWORD, "name": "Someone Else"}
        )
        check("duplicate refused", again.status_code == 409, again.status_code)
        check("and points at signing in", "Sign in" in again.json()["detail"], again.json())

        print("\n[sign out]")
        out = client.post("/api/auth/logout")
        check("logout succeeds", out.status_code == 204, out.status_code)
        check("the session no longer works", client.get("/api/stats").status_code == 401)
        check("logging out again is not an error", client.post("/api/auth/logout").status_code == 204)
        # The revoked token must stay dead even if the browser keeps it.
        client.cookies.set(settings.session_cookie_name, cookie)
        check("a revoked cookie is refused", client.get("/api/stats").status_code == 401)
        client.cookies.clear()

        print("\n[sign in]")
        bad = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong password here"})
        check("a wrong password is refused", bad.status_code == 401, bad.status_code)
        unknown = client.post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong password here"}
        )
        check(
            "an unknown address gives the identical message",
            unknown.status_code == 401 and unknown.json() == bad.json(),
            (unknown.status_code, unknown.json()),
        )
        good = client.post("/api/auth/login", json={"email": "ASHA@example.com", "password": PASSWORD})
        check("the right password signs in, case-insensitively", good.status_code == 200, good.text[:200])
        check("and it is the same account", good.json()["external_id"] == "email:" + EMAIL, good.json())
        check("the attempt from before is still theirs",
              client.get("/api/history").json()[0]["challenge_id"] == "apt-pct-001")
        client.cookies.clear()

        print("\n[guessing is throttled]")
        accounts.reset_throttle()
        codes = [
            client.post("/api/auth/login", json={"email": EMAIL, "password": f"wrong guess {i}"}).status_code
            for i in range(settings.login_attempt_limit + 2)
        ]
        check("the first attempts are plain refusals", codes[0] == 401, codes)
        check("then the address is paused", codes[-1] == 429, codes)
        locked = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        check("even the right password waits", locked.status_code == 429, locked.status_code)
        accounts.reset_throttle()
        check("and works again once the pause clears",
              client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200)
        client.cookies.clear()

        print("\n[Google, unconfigured]")
        start = client.get("/api/auth/google/start", follow_redirects=False)
        check("start refuses with 503", start.status_code == 503, start.status_code)
        check("naming the missing settings", "CLIENT_ID" in start.json()["detail"], start.json())

        print("\n[Google, configured]")
        with patch.object(settings, "google_client_id", "client-123.apps.googleusercontent.com"), \
             patch.object(settings, "google_client_secret", "secret"), \
             patch.object(settings, "google_redirect_uri", "http://localhost:5173/api/auth/google/callback"):
            check("providers now offers Google", client.get("/api/auth/providers").json()["google"] is True)
            redirect = client.get("/api/auth/google/start", follow_redirects=False)
            check("start redirects to Google", redirect.status_code == 302, redirect.status_code)
            location = redirect.headers["location"]
            for needed in ("accounts.google.com", "code_challenge=", "code_challenge_method=S256",
                           "state=", "nonce=", "scope=openid", "client_id=client-123"):
                check(f"the URL carries {needed.rstrip('=')}", needed in location, location[:160])
            state = location.split("state=")[1].split("&")[0]
            nonce = location.split("nonce=")[1].split("&")[0]

            def callback(**kwargs):
                token = kwargs.pop("token", None)
                with patch.object(google, "exchange_code", lambda code, verifier: {"id_token": token}):
                    return client.get("/api/auth/google/callback", params=kwargs, follow_redirects=False)

            print("\n[a tampered callback is refused]")
            wrong_state = callback(state="not-a-state", code="x", token=id_token(nonce=nonce))
            check("an unknown state is refused", "auth_error" in wrong_state.headers["location"],
                  wrong_state.headers["location"])
            wrong_nonce = callback(state=state, code="x", token=id_token(nonce="other-nonce"))
            check("a mismatched nonce is refused", "does+not+match" in wrong_nonce.headers["location"]
                  or "does%20not%20match" in wrong_nonce.headers["location"],
                  wrong_nonce.headers["location"])
            check("and that consumed the handshake",
                  "already+been+used" in callback(state=state, code="x", token=id_token(nonce=nonce))
                  .headers["location"].replace("%20", "+"))

            def fresh_state() -> tuple[str, str]:
                r = client.get("/api/auth/google/start", follow_redirects=False)
                loc = r.headers["location"]
                return loc.split("state=")[1].split("&")[0], loc.split("nonce=")[1].split("&")[0]

            state, nonce = fresh_state()
            wrong_aud = callback(state=state, code="x", token=id_token(nonce=nonce, aud="someone-else"))
            check("a token for another application is refused",
                  "different+application" in wrong_aud.headers["location"].replace("%20", "+"),
                  wrong_aud.headers["location"])

            state, nonce = fresh_state()
            expired = callback(
                state=state, code="x",
                token=id_token(nonce=nonce, exp=int((datetime.now(UTC) - timedelta(hours=1)).timestamp())),
            )
            check("an expired token is refused", "expired" in expired.headers["location"], expired.headers["location"])

            state, nonce = fresh_state()
            wrong_issuer = callback(state=state, code="x", token=id_token(nonce=nonce, iss="https://evil.example"))
            check("a token from another issuer is refused",
                  "not+issued+by+Google" in wrong_issuer.headers["location"].replace("%20", "+"),
                  wrong_issuer.headers["location"])

            print("\n[a good callback signs the student in]")
            client.cookies.clear()
            state, nonce = fresh_state()
            done = callback(state=state, code="x", token=id_token(nonce=nonce, sub="google-new", email="ben@gmail.com"))
            check("the browser is sent back to the app", done.status_code == 302
                  and "auth_error" not in done.headers["location"], done.headers["location"])
            me = client.get("/api/auth/me").json()
            check("and is signed in through Google", me["signed_in"] and me["provider"] == "google", me)
            check("with the Google address", me["email"] == "ben@gmail.com", me)
            check("under a google: identity", me["external_id"] == "google:google-new", me)

            print("\n[Google joins an existing password account, when verified]")
            client.cookies.clear()
            state, nonce = fresh_state()
            linked = callback(state=state, code="x", token=id_token(nonce=nonce, sub="google-asha", email=EMAIL))
            check("no error", "auth_error" not in linked.headers["location"], linked.headers["location"])
            me = client.get("/api/auth/me").json()
            check("it is the same account, not a second one",
                  me["external_id"] == "email:" + EMAIL, me)
            check("history still belongs to them",
                  client.get("/api/history").json()[0]["challenge_id"] == "apt-pct-001")

            print("\n[an unverified Google address does not join anything]")
            client.cookies.clear()
            state, nonce = fresh_state()
            unverified = callback(
                state=state, code="x",
                token=id_token(nonce=nonce, sub="google-impostor", email=EMAIL, email_verified=False),
            )
            check("sign-in still succeeds", "auth_error" not in unverified.headers["location"])
            me = client.get("/api/auth/me").json()
            check("but as a separate account", me["external_id"] == "google:google-impostor", me)

    print("\n[password hashing]")
    stored = passwords.hash_password("kettle harbour lantern")
    check("scrypt, self-describing", stored.startswith("scrypt$16384$8$1$"), stored[:24])
    check("the right password verifies", passwords.verify_password("kettle harbour lantern", stored))
    check("a wrong one does not", not passwords.verify_password("kettle harbour lantens", stored))
    check("two hashes of one password differ (fresh salt)",
          passwords.hash_password("kettle harbour lantern") != stored)
    check("no rehash needed at current parameters", not passwords.needs_rehash(stored))
    check("an older scheme is flagged for rehash", passwords.needs_rehash("scrypt$1024$8$1$aa$bb"))
    check("an empty stored hash never verifies", not passwords.verify_password("anything", ""))
    check("NFKC: the same password typed differently still matches",
          passwords.verify_password("kettle harbour lantern", passwords.hash_password("kettle harbour lantern")))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all accounts checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
