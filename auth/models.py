"""
Auth — data models.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

ADMIN_ROLES = {"bhiv-admin", "admin"}
OPERATOR_ROLES = {"operator", "bcaes-editor", "ingest:operator", "engineer"}
VIEWER_ROLES = {"viewer", "dashboard-viewer", "ecosystem-reader"}


class TokenRequest(BaseModel):
    actor: str = Field(..., min_length=1)
    roles: List[str] = Field(default_factory=list)
    password: Optional[str] = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: Optional[str] = None
    roles: Optional[List[str]] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    actor: str
    roles: List[str]
    expires_at: str


class AuthIdentity(BaseModel):
    actor: str
    roles: List[str] = Field(default_factory=list)
