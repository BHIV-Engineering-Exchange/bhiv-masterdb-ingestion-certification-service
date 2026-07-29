"""
Auth — JWT issuance and verification.

WHAT THIS IS: real signed-token infrastructure. Tokens are HS256-signed,
carry an expiry, and `decode_token` cryptographically verifies the
signature and expiry before trusting anything inside — a tampered or
expired token is rejected, not silently accepted.

WHAT THIS IS NOT: a real identity provider. `issue_token` signs whatever
`actor`/`roles` it's asked to sign — there's no password check, no SSO
handshake, nothing verifying the caller actually is who they claim. That
gap is real and is the next thing to close (see
`CANONICAL_REPOSITORY_ARCHITECTURE.md` and `PRODUCTION_HARDENING.md` for
where), but it's a materially different, larger gap than "access control
isn't enforced at all," which is what existed before this pass. Signature
verification, expiry, and per-resource role checks are all real now.

SECRET KEY: read from `AUTH_JWT_SECRET`. If unset, a random secret is
generated at process startup and a warning is logged — tokens issued by
that process instance are valid only until it restarts (fine for local
dev, wrong for anything with more than one worker process or that
restarts). Set `AUTH_JWT_SECRET` in the real environment before this is
actually production-hardened.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List

import jwt

from auth.models import AuthIdentity

logger = logging.getLogger("masterdb.auth")

_ALGORITHM = "HS256"
_DEFAULT_EXPIRY_MINUTES = 60


class AuthTokenError(Exception):
    """Raised for a missing, malformed, expired, or badly-signed token."""


class AuthService:
    def __init__(self, secret_key: str = None, expiry_minutes: int = _DEFAULT_EXPIRY_MINUTES) -> None:
        env_secret = os.environ.get("AUTH_JWT_SECRET")
        if secret_key is not None:
            self._secret_key = secret_key
        elif env_secret:
            self._secret_key = env_secret
        else:
            self._secret_key = secrets.token_hex(32)
            logger.warning(
                "AUTH_JWT_SECRET not set — generated a random per-process secret. "
                "Tokens issued by this process instance will not validate after a "
                "restart or against any other process/worker. Set AUTH_JWT_SECRET "
                "in the environment before treating this as production-hardened."
            )
        self._expiry_minutes = expiry_minutes

    def issue_token(self, actor: str, roles: List[str]) -> tuple:
        """Returns (token, expires_at_iso)."""
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self._expiry_minutes)
        payload = {
            "sub": actor,
            "roles": roles,
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=_ALGORITHM)
        return token, expires_at.isoformat()

    def decode_token(self, token: str) -> AuthIdentity:
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[_ALGORITHM])
        except jwt.ExpiredSignatureError as exc:
            raise AuthTokenError("Token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthTokenError("Token is invalid or badly signed.") from exc

        actor = payload.get("sub")
        if not actor:
            raise AuthTokenError("Token is missing a subject (actor).")
        return AuthIdentity(actor=actor, roles=payload.get("roles", []))
