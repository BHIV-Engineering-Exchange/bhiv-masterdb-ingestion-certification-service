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
    def __init__(
        self,
        secret_key: Optional[str] = None,
        expiry_minutes: Optional[int] = None,
        public_key_pem: Optional[str] = None,
    ) -> None:
        self._public_key_pem = public_key_pem
        if not self._public_key_pem:
            env_pubkey = (os.environ.get("AUTH_JWT_PUBLIC_KEY") or "").replace("\\n", "\n").strip()
            if env_pubkey:
                self._public_key_pem = env_pubkey
            else:
                key_path = os.environ.get("AUTH_JWT_PUBLIC_KEY_PATH")
                if not key_path or not os.path.exists(key_path):
                    sibling_key_path = os.path.abspath(
                        os.path.join(
                            os.path.dirname(__file__),
                            "..", "..", "..", "..", "Tantra", "TANTRA-Gated-Bridge-Infrastructure", "services", "sarathi", "keys", "public.pem"
                        )
                    )
                    if os.path.exists(sibling_key_path):
                        key_path = sibling_key_path

                if key_path and os.path.exists(key_path):
                    try:
                        with open(key_path, "r", encoding="utf-8") as fh:
                            self._public_key_pem = fh.read().strip()
                    except Exception as exc:
                        logger.warning("Could not read AUTH_JWT_PUBLIC_KEY_PATH: %s", exc)


        env_secret = (os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET") or "").strip()
        env_mode = (
            os.environ.get("ENVIRONMENT")
            or os.environ.get("APP_ENV")
            or os.environ.get("MASTERDB_ENV")
            or ""
        ).strip().lower()
        is_production = env_mode in ("production", "prod")

        if secret_key is not None:
            if not str(secret_key).strip():
                raise RuntimeError("JWT secret key cannot be empty.")
            self._secret_key = secret_key
        elif env_secret:
            self._secret_key = env_secret
        else:
            if is_production:
                raise RuntimeError(
                    "AUTH_JWT_SECRET must be configured in production mode. "
                    "Refusing to start with an ephemeral random secret."
                )
            self._secret_key = secrets.token_hex(32)
            logger.warning(
                "AUTH_JWT_SECRET not set — generated a random per-process secret (non-production mode only). "
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

    @property
    def public_key_pem(self) -> Optional[str]:
        return self._public_key_pem

    @public_key_pem.setter
    def public_key_pem(self, value: Optional[str]) -> None:
        self._public_key_pem = value.strip() if value else None

    def resolve_roles(self, actor: str, is_admin: bool = False) -> List[str]:
        """Resolves trusted server-side roles for an actor from environment configuration or defaults.

        Privileged roles (bhiv-admin, admin) are NEVER granted based solely on caller-controlled
        actor names. They require verified administrative credentials (is_admin=True).
        """
        actor_clean = actor.strip().lower()

        if is_admin:
            return ["bhiv-admin", "operator", "admin", "ingest:operator", "bcaes-editor"]

        # 1. Environment variable override for specific actor, e.g. AUTH_ROLES_KAVY="operator,ingest:relationaldb"
        env_key = f"AUTH_ROLES_{actor_clean.upper().replace('-', '_')}"
        if os.environ.get(env_key):
            assigned = [r.strip() for r in os.environ[env_key].split(",") if r.strip()]
            # Privileged roles cannot be granted via actor-name environment mapping without admin credentials
            safe_roles = [r for r in assigned if r not in {"bhiv-admin", "admin"}]
            if safe_roles:
                return safe_roles

        # 2. Configured operator actors list (if explicitly set in environment, no default fallback)
        operator_actors_env = os.environ.get("AUTH_OPERATOR_ACTORS", "").strip()
        if operator_actors_env:
            operator_actors_clean = [a.strip().lower() for a in operator_actors_env.split(",") if a.strip()]
            if actor_clean in operator_actors_clean:
                return ["operator", "bcaes-editor", "ingest:operator"]

        # Default standard roles for normal actors
        return ["viewer", "dashboard-viewer"]

    def authenticate(
        self, actor: str, password: Optional[str] = None, roles: Optional[List[str]] = None
    ) -> tuple:
        """Authenticate actor/credentials and return (token, expires_at_iso, assigned_roles).

        Fails closed if authentication password environment variables are not configured.
        Caller-supplied roles are ignored; roles are assigned only via verified server-side mechanisms.
        """
        if not actor or not str(actor).strip():
            raise AuthTokenError("Actor/username cannot be empty.")

        actor_clean = actor.strip().lower()
        auth_pw = os.environ.get("AUTH_PASSWORD") or os.environ.get("MASTERDB_AUTH_PASSWORD")
        admin_pw = os.environ.get("ADMIN_PASSWORD")

        if not auth_pw and not admin_pw:
            raise AuthTokenError(
                "Authentication is not configured on the server. Privileged token issuance requires a configured server authentication password."
            )

        is_admin_auth = False
        authenticated = False

        admin_actors = os.environ.get("AUTH_ADMIN_ACTORS", "admin,bhiv-admin,ops,kavy").split(",")
        admin_actors_clean = [a.strip().lower() for a in admin_actors if a.strip()]

        if admin_pw and password and hmac.compare_digest(str(password), str(admin_pw)):
            authenticated = True
            if actor_clean in admin_actors_clean:
                is_admin_auth = True
        elif auth_pw and password and hmac.compare_digest(str(password), str(auth_pw)):
            authenticated = True
            if not admin_pw and actor_clean in admin_actors_clean:
                is_admin_auth = True

        if not authenticated:
            raise AuthTokenError("Invalid credentials.")

        # Ignore caller-supplied roles for public authentication; obtain trusted server-side roles
        trusted_roles = self.resolve_roles(actor, is_admin=is_admin_auth)
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
            unverified_header = jwt.get_unverified_header(token)
            alg = unverified_header.get("alg")
        except Exception as exc:
            raise AuthTokenError("Token is invalid or badly signed.") from exc

        if alg == "RS256":
            public_key = self._public_key_pem or os.environ.get("AUTH_JWT_PUBLIC_KEY")
            if not public_key:
                raise AuthTokenError("Asymmetric RS256 token received but AUTH_JWT_PUBLIC_KEY is not configured.")
            try:
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )
            except jwt.ExpiredSignatureError as exc:
                raise AuthTokenError("Token has expired.") from exc
            except jwt.InvalidTokenError as exc:
                raise AuthTokenError(f"Token is invalid or badly signed: {exc}") from exc

            iss = payload.get("iss")
            if not iss or iss not in ("tantra-sarathi", "masterdb", "masterdb-production"):
                raise AuthTokenError(f"Untrusted or missing token issuer: {iss}")

            aud = payload.get("aud")
            if not aud:
                raise AuthTokenError("Token is missing required audience claim.")
            aud_list = [aud] if isinstance(aud, str) else aud
            if not any(a in ("masterdb", "tantra-bridge") for a in aud_list):
                raise AuthTokenError(f"Untrusted or invalid token audience: {aud}")

            actor = payload.get("sub") or payload.get("actor") or payload.get("trace_id")
            if not actor or not str(actor).strip():
                raise AuthTokenError("Token is missing a subject (actor).")

            roles = payload.get("roles", [])
            if not roles or not isinstance(roles, list):
                roles = ["ecosystem-reader"]

            return AuthIdentity(actor=str(actor).strip(), roles=roles)

        elif alg == _ALGORITHM:
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
        else:
            raise AuthTokenError(f"Unsupported algorithm: {alg}")
