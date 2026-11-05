"""FastAPI dependency wiring for auth. Kept separate from auth/service.py
so the service class has no FastAPI import and stays unit-testable on its
own."""
from typing import Set
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.constants import ADMIN_ROLE
from auth.models import AuthIdentity
from auth.service import AuthService, AuthTokenError

_bearer_scheme = HTTPBearer(auto_error=False)

_OPERATOR_ROLES: Set[str] = {ADMIN_ROLE, "admin", "operator", "ingest:operator", "bcaes-editor"}
_INTERNAL_ROLES: Set[str] = _OPERATOR_ROLES | {"pravah-sync", "mdu", "shared", "internal-service", "service"}


def get_identity(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> AuthIdentity:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token. Obtain one from POST /auth/token.",
        )
    try:
        import main
        active_auth = getattr(main, "auth_service", None)
        if active_auth is None:
            active_auth = AuthService()
        return active_auth.decode_token(credentials.credentials)
    except AuthTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def build_identity_dependency(auth_service: AuthService):
    return get_identity


def require_operator_or_admin(
    identity: AuthIdentity = Depends(get_identity),
) -> AuthIdentity:
    if not any(role in _OPERATOR_ROLES for role in identity.roles):
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: caller requires '{ADMIN_ROLE}' or 'operator' role.",
        )
    return identity


def require_internal_or_operator(
    identity: AuthIdentity = Depends(get_identity),
) -> AuthIdentity:
    if not any(role in _INTERNAL_ROLES for role in identity.roles):
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: caller requires internal service, operator, or '{ADMIN_ROLE}' role.",
        )
    return identity
