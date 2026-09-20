"""Production API surface protected by RS256 JWT + replay mitigation."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from security.middleware import JWTVerificationError, ProductionIdentity, RS256JWTVerifier

router = APIRouter(prefix="/production", tags=["production"])


def _get_identity(request: Request) -> ProductionIdentity:
    identity: Optional[ProductionIdentity] = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="Missing or invalid production identity.")
    return identity


class VerifyTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(..., min_length=1)


class VerifyTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str
    roles: List[str] = Field(default_factory=list)
    jti: str
    valid: bool = True


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: str
    event_type: str
    actor: str
    payload: Dict[str, Any]
    previous_hash: str
    entry_hash: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    identity: Optional[Dict[str, Any]] = None


@router.post("/verify", response_model=VerifyTokenResponse)
def verify_token(body: VerifyTokenRequest, request: Request) -> VerifyTokenResponse:
    verifier: RS256JWTVerifier = request.app.state.verifier
    try:
        payload = verifier.verify(body.token)
    except JWTVerificationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return VerifyTokenResponse(
        actor=payload.get("sub", ""),
        roles=payload.get("roles", []),
        jti=payload.get("jti", ""),
    )


@router.get("/audit", response_model=List[AuditEntryResponse])
def get_audit_log(
    request: Request, identity: ProductionIdentity = Depends(_get_identity)
) -> List[AuditEntryResponse]:
    emitter = request.app.state.audit_emitter
    entries = emitter.get_chain()
    return [
        AuditEntryResponse(
            timestamp=e.timestamp,
            event_type=e.event_type,
            actor=e.actor,
            payload=e.payload,
            previous_hash=e.previous_hash,
            entry_hash=e.entry_hash,
        )
        for e in entries
    ]


@router.get("/health", response_model=HealthResponse)
def production_health(identity: ProductionIdentity = Depends(_get_identity)) -> HealthResponse:
    return HealthResponse(status="ok", identity=identity.model_dump())
