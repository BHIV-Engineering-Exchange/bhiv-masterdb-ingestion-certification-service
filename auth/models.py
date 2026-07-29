"""
Auth — data models.

Honest scope statement (see auth/service.py module docstring for the full
picture): issuing a token here is NOT proof of who someone is — there is
no login system, no password, no SSO, no corporate identity provider
anywhere in this repo. `TokenRequest.actor`/`.roles` are self-declared by
whoever calls `/auth/token`, exactly like the `actor`/`roles` query params
they replace were self-declared before. What's real, and new, is
everything *downstream* of that: the token is cryptographically signed,
it expires, it can't be edited in transit without invalidating the
signature, and every write (and now every read, for the canonical
repository) actually checks the roles inside it against what the
resource requires. Wiring this to a real identity provider later is a
drop-in replacement for `/auth/token`'s implementation — nothing that
issues or checks tokens downstream needs to change.
"""
from typing import List

from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    actor: str
    roles: List[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    actor: str
    roles: List[str]
    expires_at: str


class AuthIdentity(BaseModel):
    actor: str
    roles: List[str] = Field(default_factory=list)
