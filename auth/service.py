"""
Auth — JWT issuance and verification.
"""
from datetime import datetime, timedelta, timezone
import hmac
import logging
import os
import secrets
from typing import List, Optional

import jwt

from auth.models import AuthIdentity

logger = logging.getLogger("masterdb.auth")

_ALGORITHM = "HS256"
_DEFAULT_EXPIRY_MINUTES = 60


class AuthTokenError(Exception):
    """Raised for a missing, malformed, expired, or badly-signed token."""


class AuthService:
    def __init__(self, secret_key: Optional[str] = None, expiry_minutes: Optional[int] = None) -> None:
        env_secret = os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET")
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

        if expiry_minutes is not None:
            self._expiry_minutes = expiry_minutes
        else:
            env_expiry = os.environ.get("AUTH_JWT_EXPIRY_MINUTES") or os.environ.get("JWT_EXPIRATION")
            try:
                self._expiry_minutes = int(env_expiry) if env_expiry else _DEFAULT_EXPIRY_MINUTES
            except ValueError:
                self._expiry_minutes = _DEFAULT_EXPIRY_MINUTES

    def resolve_roles(self, actor: str) -> List[str]:
        """Resolves trusted server-side roles for an actor from environment configuration or defaults."""
        actor_clean = actor.strip().lower()
        # 1. Environment variable override for specific actor, e.g. AUTH_ROLES_KAVY="bhiv-admin,operator"
        env_key = f"AUTH_ROLES_{actor_clean.upper().replace('-', '_')}"
        if os.environ.get(env_key):
            return [r.strip() for r in os.environ[env_key].split(",") if r.strip()]

        # 2. Configured admin actors list
        admin_actors = os.environ.get("AUTH_ADMIN_ACTORS", "admin,bhiv-admin,ops,kavy").split(",")
        admin_actors_clean = [a.strip().lower() for a in admin_actors if a.strip()]
        if actor_clean in admin_actors_clean:
            return ["bhiv-admin", "operator", "admin"]

        # 3. Configured operator actors list
        operator_actors = os.environ.get("AUTH_OPERATOR_ACTORS", "operator,engineer,dev").split(",")
        operator_actors_clean = [a.strip().lower() for a in operator_actors if a.strip()]
        if actor_clean in operator_actors_clean:
            return ["operator", "bcaes-editor", "ingest:operator"]

        # Default standard roles for normal actors
        return ["viewer", "dashboard-viewer"]

    def authenticate(
        self, actor: str, password: Optional[str] = None, roles: Optional[List[str]] = None
    ) -> tuple:
        """Authenticate actor/credentials and return (token, expires_at_iso, assigned_roles)."""
        if not actor or not str(actor).strip():
            raise AuthTokenError("Actor/username cannot be empty.")

        expected_pw = (
            os.environ.get("AUTH_PASSWORD")
            or os.environ.get("MASTERDB_AUTH_PASSWORD")
            or os.environ.get("ADMIN_PASSWORD")
        )
        if expected_pw:
            if not password or not hmac.compare_digest(str(password), str(expected_pw)):
                raise AuthTokenError("Invalid credentials.")

        # Ignore caller-supplied roles for public authentication; obtain trusted server-side roles
        trusted_roles = self.resolve_roles(actor)
        token, expires_at = self.issue_token(actor.strip(), trusted_roles)
        return token, expires_at, trusted_roles

    def issue_token(self, actor: str, roles: List[str]) -> tuple:
        """Returns (token, expires_at_iso)."""
        if not actor or not str(actor).strip():
            raise AuthTokenError("Token actor/subject cannot be empty.")

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self._expiry_minutes)
        payload = {
            "sub": str(actor).strip(),
            "roles": roles or [],
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=_ALGORITHM)
        return token, expires_at.isoformat()

    def decode_token(self, token: str) -> AuthIdentity:
        if not token or not str(token).strip():
            raise AuthTokenError("Token cannot be empty.")
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[_ALGORITHM])
        except jwt.ExpiredSignatureError as exc:
            raise AuthTokenError("Token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthTokenError("Token is invalid or badly signed.") from exc

        actor = payload.get("sub")
        if not actor or not str(actor).strip():
            raise AuthTokenError("Token is missing a subject (actor).")
        return AuthIdentity(actor=actor, roles=payload.get("roles", []))
