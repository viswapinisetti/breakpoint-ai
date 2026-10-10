"""Password hashing for email accounts.

scrypt from the standard library, not bcrypt or argon2: those ship native
wheels, and this project already has one machine where Windows Application
Control blocks unsigned native binaries. scrypt is memory-hard, is in
`hashlib`, and needs nothing installed.

Stored form, one self-describing string:

    scrypt$16384$8$1$<salt b64>$<hash b64>

The cost parameters travel with the hash, so raising them later leaves old
hashes verifiable: `needs_rehash` reports which ones to upgrade on next login.

The policy below follows NIST SP 800-63B: length is what matters, so there are
no composition rules ("one capital, one symbol"), and instead a password is
refused when it is short, when it is a well-known choice, or when it is built
from the address it protects.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata

# 128 * N * r bytes of memory: 16 MiB per hash at these settings. Enough to
# make bulk cracking expensive, small enough that a login stays fast.
SCRYPT_N = 16_384
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32
SALT_BYTES = 16
MAXMEM = 64 * 1024 * 1024

MIN_LENGTH = 10
# Bcrypt-style truncation surprises are avoided by hashing the whole string,
# but a cap keeps a megabyte "password" from becoming a denial-of-service.
MAX_LENGTH = 200

# The handful that appear at the top of every breach corpus, plus the ones
# this product invites. Not a substitute for a breach-list check, which needs
# a downloaded corpus; it catches the passwords a hurried student picks.
COMMON = frozenset(
    """
    password password1 password123 passw0rd 12345678 123456789 1234567890
    qwerty qwerty123 qwertyuiop iloveyou letmein welcome welcome1 admin123
    abc12345 111111111 000000000 dragon123 monkey123 football baseball
    breakpoint nxtwave nxtwave123 student123 changeme secret123 trustno1
    """.split()
)


class PasswordRejected(ValueError):
    """The password cannot be used. The message is shown to the student."""


def normalise(password: str) -> str:
    """NFKC, so a password typed with a different keyboard still matches."""
    return unicodedata.normalize("NFKC", password)


def check_policy(password: str, *, email: str = "", name: str = "") -> None:
    """Raise PasswordRejected if this password may not be used."""
    password = normalise(password)
    if len(password) < MIN_LENGTH:
        raise PasswordRejected(
            f"Use at least {MIN_LENGTH} characters. Length beats punctuation: "
            "a short phrase you can remember is stronger than P@ss1."
        )
    if len(password) > MAX_LENGTH:
        raise PasswordRejected(f"Use at most {MAX_LENGTH} characters.")
    if password.strip() == "":
        raise PasswordRejected("A password of only spaces will not do.")
    folded = password.casefold()
    if folded in COMMON:
        raise PasswordRejected(
            "That password appears in every list attackers try first. Pick "
            "something else."
        )
    if len(set(folded)) == 1:
        raise PasswordRejected("One repeated character is not a password.")
    local = email.split("@")[0].casefold() if email else ""
    for personal in (local, name.casefold().replace(" ", "")):
        if personal and len(personal) >= 4 and personal in folded:
            raise PasswordRejected(
                "Do not build the password out of your own name or address - "
                "it is the first thing anyone guesses."
            )


def hash_password(password: str) -> str:
    """Hash for storage. The salt is fresh per password."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(normalise(password), salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _b64(salt),
            _b64(digest),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against its stored hash.

    A malformed or empty stored value returns False rather than raising:
    accounts created through Google have no password, and a login attempt on
    one must fail like any other wrong password, not crash.
    """
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
        actual = _scrypt(normalise(password), salt, int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    """True when the stored hash uses weaker parameters than today's."""
    try:
        scheme, n, r, p, _salt, _hash = stored.split("$")
    except ValueError:
        return True
    return scheme != "scrypt" or (int(n), int(r), int(p)) != (
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
    )


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=MAXMEM
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def normalise_email(email: str) -> str:
    """Lower-cased and trimmed, which is how accounts are looked up.

    Only the domain is case-insensitive by RFC, but every provider a student
    will use treats the local part that way too, and matching addresses
    case-sensitively creates duplicate accounts for the same person.
    """
    return email.strip().casefold()


def check_email(email: str) -> str:
    """Return the normalised address, or raise PasswordRejected."""
    address = normalise_email(email)
    if not EMAIL_RE.match(address) or len(address) > 320:
        raise PasswordRejected("That does not look like an email address.")
    return address
