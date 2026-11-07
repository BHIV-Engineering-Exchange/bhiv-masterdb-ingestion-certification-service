"""FastAPI dependency wiring for auth. Kept separate from auth/service.py
so the service class has no FastAPI import and stays unit-testable on its
own."""
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.models import AuthIdentity
from auth.service import AuthService, AuthTokenError, log_security_decision

logger = logging.getLogger("masterdb.security")
_bearer_scheme = HTTPBearer(auto_error=False)


def build_identity_dependency(auth_service: AuthService):
    def get_identity(
        request: Request = None,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    ) -> AuthIdentity:
        cid = None
        path = "auth.get_identity"
        if request is not None:
            cid = (
                request.headers.get("X-Correlation-Id")
                or request.headers.get("X-Request-Id")
                or request.headers.get("X-Trace-Id")
            )
            try:
                path = request.url.path
            except Exception:
                path = "auth.get_identity"

        if credentials is None:
            log_security_decision(
                logger=logger,
                outcome="DENY",
                reason_code="DENY:MISSING_IDENTITY",
                policy_reference=path,
                actor_reference="anonymous",
                correlation_id=cid,
            )
            raise HTTPException(
                status_code=401,
                detail="DENY:MISSING_IDENTITY",
            )
        try:
            import main
            active_auth = getattr(main, "auth_service", auth_service)
            identity = active_auth.decode_token(credentials.credentials)
            log_security_decision(
                logger=logger,
                outcome="ALLOW",
                reason_code="ALLOW:VERIFIED_IDENTITY",
                policy_reference=path,
                actor_reference=identity.actor,
                correlation_id=cid,
            )
            return identity
        except AuthTokenError as exc:
            log_security_decision(
                logger=logger,
                outcome="DENY",
                reason_code="DENY:INVALID_CREDENTIALS",
                policy_reference=path,
                actor_reference="unauthenticated",
                correlation_id=cid,
            )
            raise HTTPException(status_code=401, detail=f"DENY:INVALID_CREDENTIALS: {exc}") from exc

    return get_identity


_default_auth_service = AuthService()
get_identity = build_identity_dependency(_default_auth_service)
