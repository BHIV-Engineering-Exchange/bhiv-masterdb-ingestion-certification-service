"""FastAPI dependency wiring for auth. Kept separate from auth/service.py
so the service class has no FastAPI import and stays unit-testable on its
own."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.models import AuthIdentity
from auth.service import AuthService, AuthTokenError

_bearer_scheme = HTTPBearer(auto_error=False)


def build_identity_dependency(auth_service: AuthService):
    """Returns a FastAPI dependency bound to a specific AuthService
    instance, so main.py's single `auth_service` (and its secret key) is
    what every route actually checks against — not a second, disconnected
    instance."""

    def get_identity(
        credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    ) -> AuthIdentity:
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Missing bearer token. Obtain one from POST /auth/token.",
            )
        try:
            return auth_service.decode_token(credentials.credentials)
        except AuthTokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    return get_identity
