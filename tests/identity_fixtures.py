# TEST-ONLY NON-PRODUCTION IDENTITY FIXTURES (OPTION B)
#
# NON-PRODUCTION TEST INFRASTRUCTURE ONLY:
# - Keys and tokens defined in this module are strictly for automated testing.
# - Never use these keys, tokens, or issuers in production or development environments.
# - Production authentication must fail closed if presented with tokens signed by these test keys
#   or containing the test issuer 'masterdb-test-fixture'.

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import jwt

# -----------------------------------------------------------------------------
# 1. NON-PRODUCTION RSA KEY MATERIAL (TEST USE ONLY)
# -----------------------------------------------------------------------------

TEST_RSA_PRIVATE_KEY_PEM: str = """-----BEGIN PRIVATE KEY-----
MIIEuwIBADANBgkqhkiG9w0BAQEFAASCBKUwggShAgEAAoIBAQCKlmheG9fcTjGC
H9bV6VvDduH91J9n6tTEs8yODgDopU9SkTD9lSuxN24cBEtObKFqr9KDfs7ekW8j
jVzLTXIhOfHc/HIH9Vnl7hvBaBMSDPX+11NOq0/hTru0DTd0NIJtezDbxPS9OFQp
h89g1iZD6k/rHnjPBNdIAaBNuTU+o9p6KLlQOmsmV60eWXYN/F2DXj37wJRi0lYH
LgX1HtVMdWfmDr1RzKI/XACIyQozSHJr2HyTY6xuLPEhG0DNd5NAgbtjiLCxkArx
I0/dSxGoEifhhDav76JzlCUyNqTYCmEYx7m5xS6aoKWZufa/IzIEa5GXzYDEyevO
v7Rw63RbAgMBAAECgf83ZehSYM7o7FjeAIbgUL1dun1GpLe+fSCQK09EJFTjVTFg
JVRwCYZtphAIeFmh/8qGhcH2I7qN6D+E9qfL8ilXyXyP2a8Q1K1wPBOG5xNjI8sx
vjaO5payecaOiA9NZFq+vip0WfF7B16dO1dVCPBC4GcR6scKpI9p4+cwf9hzhnWA
Vt0B2AqWPIg25PoazZs6/Bpcu+SqPyuAgtcVDkEMM5e9umF0Th0NnsCTdgUHLz/q
x3SEY5Bqqcx26/oGvY7edMh2Vomxp9lcSuSEPTP0QaQSc4F+PkERdeooIdjBYLxL
M4v2vDa/xmdDGwYfFKacBhOWvIP5xtFAMpMJq6kCgYEAwW3ECCyvJZoBk9+d6+Zd
J78UX/q/JENSeGLSw/FjcfVFFL+afXzkDfH7ViXzDV/JJ20b1XRSImrK7mvzT0WN
HR4ySVVRBZuVir46EzOrk8k1zhlAlaYk6Mz8fKGvC572ufL7MIklge+/dDPmZGBY
md031JiG0pwjXqNn/ivHUDcCgYEAt2sgPFz6472shjBS04m8SNyo7dA3ADgqY7DU
Jdihh8XJ0uBwm++Lbrccxj9HkojFekWLW1TToQOl2Ycogeva0tZkVD1yChFTM3EY
9+2r3h3riijDbyUak1jr7DtbZPhOdsU6LDdsXRJO4hYrPz+tJQT+UmV6Hp5Ug+2Z
MRhVQv0CgYBM4RPJK/lxOIToATkDScw8v/WZMFBIWXmt35llx8t+v711QbJlrf32
jPcYhnzUE/4fbX5imJkMlOWTXdSW7U3pBNd3zjElyXDmdDUg7KiFVLPN9rt0v1Rs
Mw0nfBvWwpfN0IWGBPyjaGbwCLDJtIGCpipKlVUA4I4uT0RGAaB2gQKBgEef1Z68
0FxOnShphm6EwrnRMUZsoI29YRA85RtCVRGn8wAeFNtP16sMZngkDdbzAeqVba3k
mh+uRP2FAhR5/aGHhvY+aGH2Ef9skst+TDcYh/oToP2uB4qylq5RH4d2T22h5u2N
VwuhMpym+4xfWUWzhXy3k9CRE3/RMJkzX1ghAoGBAKjU1Htkgmy85NiEUBCQyP8t
9WX9MNYsUmO9CAVitDYM8PjppuOSCITRqwbIEreYaIjUIOlcmB1o3fV8Z6Cymi8n
b5kYVGMdpKGrC8pksoadijkXu79B+85JNxUwwEUMNSewd3PBju/RfnFvdY/ly4X1
I242snuNpsX6yAfPmq/i
-----END PRIVATE KEY-----"""

TEST_RSA_PUBLIC_KEY_PEM: str = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAipZoXhvX3E4xgh/W1elb
w3bh/dSfZ+rUxLPMjg4A6KVPUpEw/ZUrsTduHARLTmyhaq/Sg37O3pFvI41cy01y
ITnx3PxyB/VZ5e4bwWgTEgz1/tdTTqtP4U67tA03dDSCbXsw28T0vThUKYfPYNYm
Q+pP6x54zwTXSAGgTbk1PqPaeii5UDprJletHll2Dfxdg149+8CUYtJWBy4F9R7V
THVn5g69UcyiP1wAiMkKM0hya9h8k2OsbizxIRtAzXeTQIG7Y4iwsZAK8SNP3UsR
qBIn4YQ2r++ic5QlMjak2AphGMe5ucUumqClmbn2vyMyBGuRl82AxMnrzr+0cOt0
WwIDAQAB
-----END PUBLIC KEY-----"""

TEST_TOKEN_ISSUER: str = "masterdb-test-fixture"
TEST_TOKEN_AUDIENCE: str = "masterdb"


# -----------------------------------------------------------------------------
# 2. TOKEN ISSUANCE HELPER (TEST USE ONLY)
# -----------------------------------------------------------------------------

def issue_fixed_test_token(
    actor: str,
    roles: Optional[List[str]] = None,
    expiry_minutes: int = 120,
    issuer: str = TEST_TOKEN_ISSUER,
    audience: str = TEST_TOKEN_AUDIENCE,
    not_before: Optional[datetime] = None,
) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=expiry_minutes)
    effective_roles = roles if roles is not None else ["ecosystem-reader", "viewer"]
    
    payload = {
        "sub": str(actor).strip(),
        "roles": effective_roles,
        "iss": issuer,
        "aud": audience,
        "exp": expires_at,
        "iat": now,
        "nbf": not_before if not_before is not None else (now - timedelta(seconds=2)),
    }
    return jwt.encode(payload, TEST_RSA_PRIVATE_KEY_PEM, algorithm="RS256")


# -----------------------------------------------------------------------------
# 3. PRE-ISSUED FIXED TEST TOKENS FOR TEST SUITE ACTORS
# -----------------------------------------------------------------------------

DEFAULT_ACTOR_ROLES: Dict[str, List[str]] = {
    "admin": ["bhiv-admin", "admin", "operator", "ingest:operator", "bcaes-editor"],
    "bhiv-admin": ["bhiv-admin", "admin", "operator", "ingest:operator", "bcaes-editor"],
    "super-admin-user": ["bhiv-admin", "admin", "operator"],
    "ops": ["operator", "bcaes-editor", "ingest:operator"],
    "kavy": ["operator", "bcaes-editor", "ingest:operator"],
    "kavy-operator": ["operator", "bcaes-editor", "ingest:operator"],
    "bcaes-editor-user": ["bcaes-editor", "operator"],
    "geo-quest-tester": ["operator", "bcaes-editor", "ingest:operator"],
    "VALID_CONSUMER": ["ecosystem-reader", "viewer"],
    "DATA_CONSUMER": ["ecosystem-reader", "viewer"],
    "auth-tester": ["ecosystem-reader", "viewer"],
    "contract-tester": ["ecosystem-reader", "viewer"],
    "test-app": ["ecosystem-reader", "viewer"],
    "grant-owner": ["ecosystem-reader", "viewer"],
    "other-actor": ["ecosystem-reader", "viewer"],
    "ATTACKER_CONSUMER": ["ecosystem-reader", "viewer"],
    "unentitled-direct-consumer": ["ecosystem-reader", "viewer"],
    "explicit-consumer": ["ecosystem-reader", "viewer"],
    "special-agent": ["ecosystem-reader", "viewer"],
    "rogue-caller": ["ecosystem-reader", "viewer"],
    "viewer": ["viewer", "ecosystem-reader"],
    "test-viewer": ["viewer", "ecosystem-reader"],
    "candidate-viewer": ["ecosystem-reader", "viewer"],
    "candidate-reviewer": ["ecosystem-reader", "viewer"],
    "gev-viewer": ["ecosystem-reader", "viewer"],
    "domain-tester": ["ecosystem-reader", "viewer"],
    "vana-tester": ["ecosystem-reader", "viewer"],
    "tantra-execution": ["ecosystem-reader", "viewer"],
    "tantra-execution-agent": ["ecosystem-reader", "viewer"],
    "masterdb-test-consumer": ["ecosystem-reader", "viewer"],
    "test-actor": ["ecosystem-reader", "viewer"],
}

_FIXED_TEST_TOKEN_CACHE: Dict[str, str] = {}


def get_test_token(actor: str = "test-actor", roles: Optional[List[str]] = None) -> str:
    key_roles = ",".join(roles) if roles is not None else "default"
    cache_key = f"{actor}::{key_roles}"
    if cache_key not in _FIXED_TEST_TOKEN_CACHE:
        assigned_roles = roles if roles is not None else DEFAULT_ACTOR_ROLES.get(actor, ["ecosystem-reader", "viewer"])
        _FIXED_TEST_TOKEN_CACHE[cache_key] = issue_fixed_test_token(actor=actor, roles=assigned_roles)
    return _FIXED_TEST_TOKEN_CACHE[cache_key]


def get_test_auth_headers(actor: str = "test-actor", roles: Optional[List[str]] = None) -> Dict[str, str]:
    token = get_test_token(actor=actor, roles=roles)
    return {"Authorization": f"Bearer {token}"}
