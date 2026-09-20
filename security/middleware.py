"""Enterprise security middleware: JWT RS256 + replay mitigation."""
import os
import threading
import time
from typing import Any, Dict, List, Optional

import jwt
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def _error_response(request: Request, status_code: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"type": error_type, "message": message, "path": str(request.url.path)}},
    )


class ReplayMitigationTable:
    """Thread-safe ledger of consumed JWT jti values."""

    def __init__(self, max_size: int = 10_000) -> None:
        self._table: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_size = max_size

    def register(self, jti: str, exp: float) -> bool:
        with self._lock:
            self._cleanup()
            if jti in self._table:
                return False
            self._table[jti] = float(exp)
            if len(self._table) > self._max_size:
                sorted_items = sorted(self._table.items(), key=lambda kv: kv[1])
                self._table = dict(sorted_items[len(sorted_items) // 2:])
            return True

    def _cleanup(self) -> None:
        now = time.time()
        for jti in [k for k, v in self._table.items() if v < now]:
            del self._table[jti]

    def count(self) -> int:
        with self._lock:
            self._cleanup()
            return len(self._table)


class JWTVerificationError(Exception):
    """Token failed RS256 verification."""


class RS256JWTVerifier:
    def __init__(self, public_key_pem: Optional[str] = None) -> None:
        pem: Optional[str] = public_key_pem
        if pem is None:
            pem = os.environ.get("AUTH_JWT_PUBLIC_KEY", "").replace("\\n", "\n")
            if not pem:
                key_path = os.environ.get("AUTH_JWT_PUBLIC_KEY_PATH")
                if key_path and os.path.exists(key_path):
                    with open(key_path, "r", encoding="utf-8") as fh:
                        pem = fh.read()
        if not pem:
            pem = self._generate_fallback_public_key()
        self._public_key_pem = pem

    @staticmethod
    def _generate_fallback_public_key() -> str:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def verify(self, token: str) -> Dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self._public_key_pem,
                algorithms=["RS256"],
                options={"require": ["exp", "sub", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise JWTVerificationError("Token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise JWTVerificationError("Token is invalid or badly signed.") from exc
        return payload


class ProductionIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(..., min_length=1)
    roles: List[str] = Field(default_factory=list)
    jti: str = Field(..., min_length=1)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        verifier: Optional[RS256JWTVerifier] = None,
        replay_table: Optional[ReplayMitigationTable] = None,
    ) -> None:
        super().__init__(app)
        self.verifier = verifier or RS256JWTVerifier()
        self.replay_table = replay_table or ReplayMitigationTable()

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/production/"):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return _error_response(request, 401, "auth_error", "Missing bearer token.")

        token = auth_header.split(" ", 1)[1]
        try:
            payload = self.verifier.verify(token)
        except JWTVerificationError as exc:
            return _error_response(request, 401, "auth_error", str(exc))

        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti is None or exp is None:
            return _error_response(request, 401, "auth_error", "Token missing jti or exp.")

        if not self.replay_table.register(jti, float(exp)):
            return _error_response(request, 403, "replay_error", "Token replay detected.")

        request.state.identity = ProductionIdentity(
            actor=payload.get("sub", ""),
            roles=payload.get("roles", []),
            jti=jti,
        )

        return await call_next(request)

