"""
Auth — JWT issuance and verification.
"""
from datetime import datetime, timedelta, timezone
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional
import uuid

import jwt

from auth.models import AuthIdentity
from security.public_key import load_rsa_public_key

logger = logging.getLogger("masterdb.auth")

# ---------------------------------------------------------------------------
# Configuration – algorithm selection (environment controlled)
# ---------------------------------------------------------------------------
_JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "RS256").upper()

if _JWT_ALGORITHM not in ("RS256", "HS256"):
    raise RuntimeError(f"Unsupported JWT_ALGORITHM={_JWT_ALGORITHM}")

# The constant used by the rest of the module – we keep the old name for backward
# compatibility but force it to reflect the configured algorithm.
_ALGORITHM = _JWT_ALGORITHM

_DEFAULT_EXPIRY_MINUTES = 60


class AuthTokenError(Exception):
    """Raised for a missing, malformed, expired, or badly-signed token."""


def log_security_decision(
    logger: logging.Logger,
    outcome: str,
    reason_code: str,
    policy_reference: str,
    actor_reference: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Structured security decision logger following MASTERDB audit conventions."""
    cid = correlation_id or uuid.uuid4().hex
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": cid,
        "request_id": cid,
        "outcome": outcome,
        "reason_code": reason_code,
        "policy_reference": policy_reference,
        "actor_reference": actor_reference or "anonymous",
    }
    msg = json.dumps(record, sort_keys=True)
    if outcome == "DENY":
        logger.warning("SECURITY_DECISION: %s", msg)
    else:
        logger.info("SECURITY_DECISION: %s", msg)
    return record


def validate_rsa_public_key(pem_str: str) -> None:
    if not pem_str or not pem_str.strip():
        raise RuntimeError("Authoritative RS256 public key is empty.")
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = load_pem_public_key(pem_str.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Authoritative RS256 public key is malformed or invalid: {exc}") from exc
    if not isinstance(key, rsa.RSAPublicKey):
        raise RuntimeError("Authoritative RS256 public key is malformed or invalid: Key must be RSA.")
    if key.key_size < 2048:
        raise RuntimeError("Authoritative RS256 public key has insufficient key size (< 2048 bits).")


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

        # 1. Enforce production has a configured secret before algorithm check
        if is_production and not (secret_key or env_secret):
            raise RuntimeError(
                "AUTH_JWT_SECRET must be configured in production mode. "
                "Refusing to start with an ephemeral random secret."
            )

        # 2. Enforce production rejects HS256 configuration
        configured_alg = os.environ.get("JWT_ALGORITHM")
        if is_production and configured_alg and configured_alg.strip().upper() == "HS256":
            raise RuntimeError("Production environment must use RS256 algorithm for JWTs")

        # 3. Enforce production has an authoritative RS256 public key
        if is_production:
            if not self._public_key_pem:
                raise RuntimeError("AUTH_JWT_PUBLIC_KEY or AUTH_JWT_PUBLIC_KEY_PATH must be configured in production mode.")
            try:
                validate_rsa_public_key(self._public_key_pem)
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "insufficient" in msg or "2048" in msg:
                    raise RuntimeError(f"Authoritative RS256 public key has insufficient key size: {exc}") from exc
                raise RuntimeError(f"Authoritative RS256 public key is malformed or invalid: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(f"Authoritative RS256 public key is malformed or invalid: {exc}") from exc

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
    def is_production(self) -> bool:
        env_mode = (
            os.environ.get("ENVIRONMENT")
            or os.environ.get("APP_ENV")
            or os.environ.get("MASTERDB_ENV")
            or ""
        ).strip().lower()
        return env_mode in ("production", "prod")

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
        if self.is_production:
            raise AuthTokenError("Local token issuance is prohibited in production mode.")

        if not (os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET")):
            raise AuthTokenError("AUTH_JWT_SECRET is not explicitly configured; refusing fallback.")

        if not actor or not str(actor).strip():
            raise AuthTokenError("Actor/username cannot be empty.")

        actor_clean = actor.strip().lower()

        allowed_actors_env = os.environ.get("AUTH_ALLOWED_ACTORS")
        if allowed_actors_env is None:
            raise AuthTokenError("AUTH_ALLOWED_ACTORS must be configured for local token issuance.")
        allowed_actors = [a.strip().lower() for a in allowed_actors_env.split(",") if a.strip()]
        if actor_clean not in allowed_actors:
            raise AuthTokenError(f"Actor '{actor}' is not authorized for local token issuance.")

        auth_pw = os.environ.get("AUTH_PASSWORD") or os.environ.get("MASTERDB_AUTH_PASSWORD")
        admin_pw = os.environ.get("ADMIN_PASSWORD")

        if not auth_pw and not admin_pw:
            log_security_decision(
                logger=logger,
                outcome="DENY",
                reason_code="DENY:SERVER_AUTH_NOT_CONFIGURED",
                policy_reference="auth.service.authenticate",
                actor_reference=actor,
            )
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
            if not admin_pw and actor_clean in admin_actors_clean:
                log_security_decision(
                    logger=logger,
                    outcome="DENY",
                    reason_code="DENY:MISSING_ADMIN_PASSWORD",
                    policy_reference="auth.service.authenticate",
                    actor_reference=actor,
                )
                raise AuthTokenError("DENY:MISSING_ADMIN_PASSWORD")
            authenticated = True

        if not authenticated:
            log_security_decision(
                logger=logger,
                outcome="DENY",
                reason_code="DENY:INVALID_CREDENTIALS",
                policy_reference="auth.service.authenticate",
                actor_reference=actor,
            )
            raise AuthTokenError("Invalid credentials.")

        # Ignore caller-supplied roles for public authentication; obtain trusted server-side roles
        trusted_roles = self.resolve_roles(actor, is_admin=is_admin_auth)
        token, expires_at = self.issue_token(actor.strip(), trusted_roles)
        log_security_decision(
            logger=logger,
            outcome="ALLOW",
            reason_code="ALLOW:AUTHENTICATED",
            policy_reference="auth.service.authenticate",
            actor_reference=actor,
        )
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
            "aud": "masterdb",
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self._secret_key, algorithm="HS256")
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
                rsa_public_key = load_rsa_public_key(public_key)
                payload = jwt.decode(
                    token,
                    rsa_public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False, "verify_nbf": True},
                )
            except jwt.ExpiredSignatureError as exc:
                raise AuthTokenError("Token has expired.") from exc
            except jwt.ImmatureSignatureError as exc:
                raise AuthTokenError(f"Token is not yet valid (nbf/iat): {exc}") from exc
            except jwt.InvalidTokenError as exc:
                raise AuthTokenError(f"Token is invalid or badly signed: {exc}") from exc
            except (TypeError, ValueError) as exc:
                raise AuthTokenError(f"RS256 public key is invalid: {exc}") from exc

            # iat skew validation (>300s in future)
            iat = payload.get("iat")
            if iat is not None:
                iat_ts = iat.timestamp() if isinstance(iat, datetime) else float(iat)
                if iat_ts > time.time() + 300:
                    raise AuthTokenError("Token issued in the future (iat skew exceeds limit).")

            # sub validation: strictly required, non-empty string, no actor/trace_id fallbacks
            sub = payload.get("sub")
            if not sub or not isinstance(sub, str) or not sub.strip():
                raise AuthTokenError("Token is missing a subject (actor).")

            # iss validation
            iss = payload.get("iss")
            if not isinstance(iss, str) or not iss.strip():
                raise AuthTokenError("Untrusted or missing token issuer: missing")
            if self.is_production and iss == "masterdb-test-fixture":
                raise AuthTokenError("Test token issuer 'masterdb-test-fixture' is prohibited in production mode.")

            env_issuers = [x.strip() for x in (os.environ.get("AUTH_ISSUER") or "").split(",") if x.strip()]
            allowed_issuers = set(env_issuers) if env_issuers else {
                "tantra-sarathi", "masterdb", "masterdb-production"
            }
            if not env_issuers and not self.is_production:
                allowed_issuers.update({"masterdb-test-fixture", "masterdb-local"})
            if self.is_production:
                allowed_issuers.discard("masterdb-test-fixture")

            if iss not in allowed_issuers:
                raise AuthTokenError(f"Untrusted or missing token issuer: {iss}")

            # aud validation
            aud = payload.get("aud")
            if not aud:
                raise AuthTokenError("Token is missing required audience claim.")
            if isinstance(aud, str):
                aud_list = [aud]
            elif isinstance(aud, list) and all(isinstance(item, str) for item in aud):
                aud_list = aud
            else:
                raise AuthTokenError("Token audience claim must be a string or a list of strings.")
            env_aud_value = os.environ.get("AUTH_JWT_AUDIENCE") or os.environ.get("AUTH_AUDIENCE") or ""
            env_aud = [x.strip() for x in env_aud_value.split(",") if x.strip()]
            allowed_audiences = set(env_aud) if env_aud else {
                "masterdb", "tantra-bridge", "masterdb-production"
            }
            if not any(a in allowed_audiences for a in aud_list):
                raise AuthTokenError(f"Untrusted or invalid token audience: {aud}")

            # roles validation
            roles = payload.get("roles")
            if roles is None or not isinstance(roles, list):
                raise AuthTokenError("Token is missing required roles claim.")
            valid_roles = [r for r in roles if isinstance(r, str) and r.strip()]
            if not valid_roles:
                raise AuthTokenError("Token contains no valid roles.")

            is_tantra = iss in ("tantra-sarathi", "masterdb-test-fixture", "masterdb", "masterdb-production")
            return AuthIdentity(
                actor=sub.strip(),
                roles=valid_roles,
                auth_method="RS256",
                issuer=iss,
                is_tantra_verified=is_tantra,
            )

        elif alg == "HS256":
            if self.is_production:
                raise AuthTokenError("HS256 symmetric tokens are rejected in production mode.")
            try:
                payload = jwt.decode(token, self._secret_key, algorithms=["HS256"], options={"verify_aud": False})
            except jwt.ExpiredSignatureError as exc:
                raise AuthTokenError("Token has expired.") from exc
            except jwt.InvalidTokenError as exc:
                raise AuthTokenError("Token is invalid or badly signed.") from exc

            sub = payload.get("sub")
            if not sub or not isinstance(sub, str) or not sub.strip():
                raise AuthTokenError("Token is missing a subject (actor).")
            return AuthIdentity(
                actor=sub.strip(),
                roles=payload.get("roles", []),
                auth_method="HS256",
                issuer=payload.get("iss", "masterdb-local"),
                is_tantra_verified=False,
            )
        else:
            raise AuthTokenError(f"Unsupported algorithm: {alg}")
