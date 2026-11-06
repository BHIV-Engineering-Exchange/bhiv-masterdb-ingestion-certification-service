"""
Auth — JWT issuance and verification.
"""
from datetime import datetime, timedelta, timezone
import hmac
import logging
import os
import secrets
from typing import List, Optional

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key
import jwt

from auth.models import AuthIdentity
from security.public_key import load_rsa_public_key

logger = logging.getLogger("masterdb.auth")

_ALGORITHM = "HS256"
_DEFAULT_EXPIRY_MINUTES = 60


class AuthTokenError(Exception):
    """Raised for a missing, malformed, expired, or badly-signed token."""


def validate_rsa_public_key(pem_str: str) -> None:
    """Validates that a PEM string contains a valid RSA public key of at least 2048 bits."""
    if not pem_str or not pem_str.strip():
        raise RuntimeError("Authoritative RS256 public key is empty.")
    try:
        key = load_pem_public_key(pem_str.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Authoritative RS256 public key is malformed or invalid: {exc}") from exc

    if not isinstance(key, rsa.RSAPublicKey):
        raise RuntimeError("Authoritative public key must be an RSA public key (RS256).")

    if key.key_size < 2048:
        raise RuntimeError(
            f"Authoritative RS256 public key size ({key.key_size} bits) is insufficient. "
            "Minimum 2048 bits required."
        )


class AuthService:
    def __init__(
        self,
        secret_key: Optional[str] = None,
        expiry_minutes: Optional[int] = None,
        public_key_pem: Optional[str] = None,
    ) -> None:
        self._explicit_secret_key: Optional[str] = None
        if secret_key is not None:
            if not str(secret_key).strip():
                raise RuntimeError("JWT secret key cannot be empty.")
            self._explicit_secret_key = str(secret_key).strip()

        self._public_key_pem = public_key_pem.strip() if public_key_pem else None
        if not self._public_key_pem:
            env_pubkey = (os.environ.get("AUTH_JWT_PUBLIC_KEY") or "").replace("\\n", "\n").strip()
            if env_pubkey:
                self._public_key_pem = env_pubkey
            else:
                key_path = (os.environ.get("AUTH_JWT_PUBLIC_KEY_PATH") or "").strip()
                if key_path:
                    if os.path.exists(key_path):
                        try:
                            with open(key_path, "r", encoding="utf-8") as fh:
                                self._public_key_pem = fh.read().strip()
                        except Exception as exc:
                            logger.warning("Could not read AUTH_JWT_PUBLIC_KEY_PATH: %s", exc)
                    else:
                        logger.warning("Configured AUTH_JWT_PUBLIC_KEY_PATH does not exist: %s", key_path)

        env_secret = (os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET") or "").strip()
        env_mode = (
            os.environ.get("ENVIRONMENT")
            or os.environ.get("APP_ENV")
            or os.environ.get("MASTERDB_ENV")
            or ""
        ).strip().lower()
        is_production = env_mode in ("production", "prod")

        if is_production and not (self._explicit_secret_key or env_secret):
            raise RuntimeError(
                "AUTH_JWT_SECRET must be configured in production mode. "
                "Refusing to start with an ephemeral random secret."
            )

        if is_production:
            if not self._public_key_pem:
                raise RuntimeError(
                    "AUTH_JWT_PUBLIC_KEY or AUTH_JWT_PUBLIC_KEY_PATH must be configured in production mode. "
                    "Refusing to start without authoritative RS256 public key."
                )
            validate_rsa_public_key(self._public_key_pem)

        self._ephemeral_secret = secrets.token_hex(32)
        if not (self._explicit_secret_key or env_secret) and not is_production:
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
    def env_mode(self) -> str:
        return (
            os.environ.get("ENVIRONMENT")
            or os.environ.get("APP_ENV")
            or os.environ.get("MASTERDB_ENV")
            or ""
        ).strip().lower()

    @property
    def is_production(self) -> bool:
        return self.env_mode in ("production", "prod")

    @property
    def is_dev_or_test(self) -> bool:
        return self.env_mode in ("development", "dev", "test", "testing", "local")

    @property
    def has_explicit_secret(self) -> bool:
        if self._explicit_secret_key:
            return True
        env_secret = (os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET") or "").strip()
        return bool(env_secret)

    @property
    def secret_key(self) -> str:
        if self._explicit_secret_key:
            return self._explicit_secret_key
        env_secret = (os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET") or "").strip()
        if env_secret:
            return env_secret
        if self.is_production:
            raise RuntimeError(
                "AUTH_JWT_SECRET must be configured in production mode. "
                "Refusing to use an ephemeral random secret."
            )
        return self._ephemeral_secret

    @property
    def _secret_key(self) -> str:
        return self.secret_key

    @property
    def public_key_pem(self) -> Optional[str]:
        if self._public_key_pem:
            return self._public_key_pem
        env_pubkey = (os.environ.get("AUTH_JWT_PUBLIC_KEY") or "").replace("\\n", "\n").strip()
        if env_pubkey:
            return env_pubkey
        key_path = (os.environ.get("AUTH_JWT_PUBLIC_KEY_PATH") or "").strip()
        if key_path:
            if os.path.exists(key_path):
                try:
                    with open(key_path, "r", encoding="utf-8") as fh:
                        return fh.read().strip()
                except Exception as exc:
                    logger.warning("Could not read AUTH_JWT_PUBLIC_KEY_PATH: %s", exc)
            else:
                logger.warning("Configured AUTH_JWT_PUBLIC_KEY_PATH does not exist: %s", key_path)
        return None

    @public_key_pem.setter
    def public_key_pem(self, value: Optional[str]) -> None:
        cleaned = value.strip() if value else None
        if self.is_production and cleaned:
            validate_rsa_public_key(cleaned)
        self._public_key_pem = cleaned

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
        # 1. Reject local token issuance in production mode
        if self.is_production:
            raise AuthTokenError(
                "Local token issuance is prohibited in production mode. "
                "Production callers must use TANTRA Sarathi RS256 authentication."
            )

        # 2. Reject if environment is not explicitly development or test
        if not self.is_dev_or_test:
            raise AuthTokenError(
                "Local token issuance is permitted only in explicitly configured development or test environments."
            )

        # 3. Reject if local signing secret is not explicitly configured
        if not self.has_explicit_secret:
            raise AuthTokenError(
                "AUTH_JWT_SECRET is not explicitly configured. "
                "Local token issuance requires an explicit secret."
            )

        if not actor or not str(actor).strip():
            raise AuthTokenError("Actor/username cannot be empty.")

        actor_clean = actor.strip().lower()

        # 4. Server-side actor allowlist check with normalized variant matching
        allowed_actors_env = (os.environ.get("AUTH_ALLOWED_ACTORS") or "").strip()
        if not allowed_actors_env:
            raise AuthTokenError(
                "AUTH_ALLOWED_ACTORS must be configured for local token issuance."
            )
        allowed_actors = {a.strip().lower() for a in allowed_actors_env.split(",") if a.strip()}
        actor_variants = {
            actor_clean,
            actor_clean.replace("-", "_"),
            actor_clean.replace("_", "-"),
            actor_clean.replace(" ", "_"),
            actor_clean.replace(" ", "-"),
        }
        if not any(v in allowed_actors for v in actor_variants):
            raise AuthTokenError(
                f"Actor '{actor}' is not authorized for local token issuance."
            )

        # 5. Server authentication credentials check
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
            "iss": "masterdb-local",
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self.secret_key, algorithm=_ALGORITHM)
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
            public_key = self.public_key_pem
            if not public_key:
                raise AuthTokenError("Asymmetric RS256 token received but AUTH_JWT_PUBLIC_KEY is not configured.")
            try:
                rsa_public_key = load_rsa_public_key(public_key)
                payload = jwt.decode(
                    token,
                    rsa_public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False, "verify_iss": False},
                )
            except jwt.ExpiredSignatureError as exc:
                raise AuthTokenError("Token has expired.") from exc
            except jwt.ImmatureSignatureError as exc:
                raise AuthTokenError(f"Token is not yet valid: {exc}") from exc
            except jwt.InvalidTokenError as exc:
                raise AuthTokenError(f"Token is invalid or badly signed: {exc}") from exc
            except (TypeError, ValueError) as exc:
                raise AuthTokenError(f"RS256 public key is invalid: {exc}") from exc

            # Validate temporal claims (nbf and iat clock skew)
            now = datetime.now(timezone.utc).timestamp()
            nbf = payload.get("nbf")
            if nbf is not None:
                try:
                    if float(nbf) > now + 1:
                        raise AuthTokenError("Token is not yet valid (nbf in future).")
                except (ValueError, TypeError):
                    raise AuthTokenError("Token contains malformed nbf claim.")

            iat = payload.get("iat")
            if iat is not None:
                try:
                    if float(iat) > now + 300:
                        raise AuthTokenError("Token issued in the future (iat clock skew > 300s).")
                except (ValueError, TypeError):
                    raise AuthTokenError("Token contains malformed iat claim.")

            # Validate Issuer
            env_issuer = (os.environ.get("AUTH_ISSUER") or "").strip()
            default_issuers = {"tantra-sarathi", "masterdb", "masterdb-production"}
            if env_issuer:
                allowed_issuers = {i.strip() for i in env_issuer.split(",") if i.strip()} | default_issuers
            else:
                allowed_issuers = default_issuers

            iss = payload.get("iss")
            if not iss:
                raise AuthTokenError("Untrusted or missing token issuer: None")
            if self.is_production and iss == "masterdb-test-fixture":
                raise AuthTokenError(f"Test token issuer '{iss}' is prohibited in production mode.")
            if iss not in allowed_issuers:
                raise AuthTokenError(f"Untrusted or missing token issuer: {iss}")

            # Validate Audience
            env_aud = (os.environ.get("AUTH_AUDIENCE") or "").strip()
            default_audiences = {"masterdb", "tantra-bridge"}
            if env_aud:
                allowed_audiences = {a.strip() for a in env_aud.split(",") if a.strip()} | default_audiences
            else:
                allowed_audiences = default_audiences

            aud = payload.get("aud")
            if not aud:
                raise AuthTokenError("Token is missing required audience claim.")
            aud_list = [aud] if isinstance(aud, str) else list(aud)
            if not any(a in allowed_audiences for a in aud_list):
                raise AuthTokenError(f"Untrusted or invalid token audience: {aud}")

            sub = payload.get("sub")
            if sub is None or not isinstance(sub, str) or not sub.strip():
                raise AuthTokenError("Token is missing a subject: 'sub' claim must exist and be a non-empty string.")
            actor = sub.strip()

            roles = payload.get("roles")
            if roles is None or not isinstance(roles, list):
                raise AuthTokenError("Token is missing required roles claim.")

            safe_roles = [r for r in roles if r in (
                "ecosystem-reader", "viewer", "dashboard-viewer",
                "operator", "bcaes-editor", "ingest:operator", "engineer",
                "APPROVED_CONSUMER", "admin", "bhiv-admin"
            )]
            if not safe_roles:
                raise AuthTokenError("Token contains no valid roles.")

            return AuthIdentity(
                actor=str(actor).strip(),
                roles=safe_roles,
                auth_method="RS256",
                issuer=str(iss),
                is_tantra_verified=True,
            )

        elif alg == _ALGORITHM:
            if self.is_production:
                raise AuthTokenError(
                    "HS256 symmetric tokens are rejected in production mode. "
                    "Cryptographically verified TANTRA RS256 token required."
                )

            try:
                payload = jwt.decode(token, self.secret_key, algorithms=[_ALGORITHM])
            except jwt.ExpiredSignatureError as exc:
                raise AuthTokenError("Token has expired.") from exc
            except jwt.InvalidTokenError as exc:
                raise AuthTokenError("Token is invalid or badly signed.") from exc

            sub = payload.get("sub")
            if sub is None or not isinstance(sub, str) or not sub.strip():
                raise AuthTokenError("Token is missing a subject: 'sub' claim must exist and be a non-empty string.")
            actor = sub.strip()

            roles = payload.get("roles", [])
            if not isinstance(roles, list):
                roles = []

            return AuthIdentity(
                actor=str(actor).strip(),
                roles=roles,
                auth_method="HS256",
                issuer=payload.get("iss", "masterdb-local"),
                is_tantra_verified=False,
            )
        else:
            raise AuthTokenError(f"Unsupported algorithm: {alg}")
