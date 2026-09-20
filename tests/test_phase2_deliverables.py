"""Comprehensive tests for Phase 2 deliverables."""
import hashlib
import json
import time
from typing import Any, Dict

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.production import router as production_router
from evaluation_engine.rule_engine import RuleEngine, RuleResult
from integrations.local_llm_client import LLMRequest, LocalLLMClient
from security.middleware import (
    JWTVerificationError,
    ProductionIdentity,
    ReplayMitigationTable,
    RS256JWTVerifier,
    SecurityMiddleware,
    _error_response,
)
from services.crypto_audit_emitter import AuditEntry, CryptoAuditEmitter
from task_selector.review_orchestrator import ReviewOrchestrator


# ---------------------------------------------------------------------------
# RS256 JWT Verifier
# ---------------------------------------------------------------------------

@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


@pytest.fixture
def jwt_payload():
    return {"sub": "actor-1", "roles": ["admin"], "jti": "jti-123", "exp": int(time.time()) + 300}


def test_rs256_verifier_accepts_valid_token(rsa_keypair, jwt_payload):
    priv, pub = rsa_keypair
    token = jwt.encode(jwt_payload, priv, algorithm="RS256")
    verifier = RS256JWTVerifier(public_key_pem=pub)
    payload = verifier.verify(token)
    assert payload["sub"] == jwt_payload["sub"]
    assert payload["jti"] == jwt_payload["jti"]


def test_rs256_verifier_rejects_expired_token(rsa_keypair, jwt_payload):
    priv, pub = rsa_keypair
    jwt_payload["exp"] = int(time.time()) - 10
    token = jwt.encode(jwt_payload, priv, algorithm="RS256")
    verifier = RS256JWTVerifier(public_key_pem=pub)
    with pytest.raises(JWTVerificationError, match="expired"):
        verifier.verify(token)


def test_rs256_verifier_rejects_tampered_token(rsa_keypair, jwt_payload):
    priv, pub = rsa_keypair
    token = jwt.encode(jwt_payload, priv, algorithm="RS256")
    verifier = RS256JWTVerifier(public_key_pem=pub)
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(JWTVerificationError, match="invalid"):
        verifier.verify(tampered)


# ---------------------------------------------------------------------------
# Replay Mitigation Table
# ---------------------------------------------------------------------------

@pytest.fixture
def replay_table():
    return ReplayMitigationTable()


def test_replay_table_allows_first_use(replay_table):
    assert replay_table.register("jti-1", float(int(time.time()) + 300)) is True


def test_replay_table_rejects_reuse(replay_table):
    exp = float(int(time.time()) + 300)
    assert replay_table.register("jti-1", exp) is True
    assert replay_table.register("jti-1", exp) is False


def test_replay_table_different_jti(replay_table):
    assert replay_table.register("jti-a", float(int(time.time()) + 300)) is True
    assert replay_table.register("jti-b", float(int(time.time()) + 300)) is True


# ---------------------------------------------------------------------------
# Crypto Audit Emitter
# ---------------------------------------------------------------------------

def test_audit_emitter_chain_integrity():
    emitter = CryptoAuditEmitter()
    entry1 = emitter.emit("ev1", "actor1", {"k": "v1"})
    entry2 = emitter.emit("ev2", "actor1", {"k": "v2"})
    assert entry2.previous_hash == entry1.entry_hash
    assert emitter.verify_chain() is True


def test_audit_emitter_tampering_detected():
    emitter = CryptoAuditEmitter()
    emitter.emit("ev1", "actor1", {"k": "v1"})
    emitter.emit("ev2", "actor1", {"k": "v2"})
    # Tamper with the internal chain directly
    original = emitter._chain[0]
    tampered = AuditEntry(
        timestamp=original.timestamp,
        event_type="tampered",
        actor=original.actor,
        payload=original.payload,
        previous_hash=original.previous_hash,
        entry_hash=original.entry_hash,
    )
    emitter._chain[0] = tampered
    assert emitter.verify_chain() is False


def test_audit_emitter_state_hash():
    emitter = CryptoAuditEmitter()
    assert emitter.state_hash == hashlib.sha256(b"").hexdigest()
    entry = emitter.emit("ev1", "actor1", {})
    assert emitter.state_hash == entry.entry_hash


# ---------------------------------------------------------------------------
# Rule Engine
# ---------------------------------------------------------------------------

def test_rule_engine_passing():
    engine = RuleEngine()
    engine.register_rule("approved", lambda ctx: ctx.get("score", 0) > 50)
    result = engine.evaluate({"score": 75}, "approved")
    assert isinstance(result, RuleResult)
    assert result.passed is True
    assert result.reason == "Rule passed"


def test_rule_engine_failing():
    engine = RuleEngine()
    engine.register_rule("approved", lambda ctx: ctx.get("score", 0) > 50)
    result = engine.evaluate({"score": 30}, "approved")
    assert result.passed is False
    assert result.reason == "Rule failed"


def test_rule_engine_missing_rule():
    engine = RuleEngine()
    result = engine.evaluate({}, "missing")
    assert result.passed is False
    assert "No rule registered" in result.reason


def test_rule_engine_exception_in_rule():
    engine = RuleEngine()
    engine.register_rule("bad", lambda ctx: 1 / 0)
    result = engine.evaluate({}, "bad")
    assert result.passed is False
    assert "Rule evaluation error" in result.reason


# ---------------------------------------------------------------------------
# Local LLM Client (Circuit Breaker)
# ---------------------------------------------------------------------------

def test_llm_client_not_configured():
    client = LocalLLMClient(endpoint="")
    assert client.is_configured() is False
    with pytest.raises(RuntimeError, match="not configured"):
        client.analyze(LLMRequest(prompt="hello"))


# ---------------------------------------------------------------------------
# Review Orchestrator
# ---------------------------------------------------------------------------

def test_review_orchestrator_evaluates_and_audits():
    rule_engine = RuleEngine()
    rule_engine.register_rule("ok", lambda ctx: True)
    orchestrator = ReviewOrchestrator(rule_engine=rule_engine)
    result = orchestrator.evaluate_task("t-1", {}, "ok", actor="tester")
    assert result["task_id"] == "t-1"
    assert result["rule_result"].passed is True
    assert orchestrator.audit_emitter.get_chain()[-1].event_type == "task_evaluation"


# ---------------------------------------------------------------------------
# Production API Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def production_app(rsa_keypair):
    priv, pub = rsa_keypair
    app = FastAPI()
    verifier = RS256JWTVerifier(public_key_pem=pub)
    app.state.verifier = verifier
    app.state.audit_emitter = CryptoAuditEmitter()
    app.add_middleware(SecurityMiddleware, verifier=verifier, replay_table=ReplayMitigationTable())
    app.include_router(production_router)
    return app


@pytest.mark.asyncio
async def test_production_health_requires_auth(production_app):
    async with AsyncClient(transport=ASGITransport(app=production_app), base_url="http://test") as client:
        response = await client.get("/production/health")
        assert response.status_code == 401
        data = response.json()
        assert data["error"]["type"] == "auth_error"


@pytest.mark.asyncio
async def test_production_verify_endpoint(production_app, rsa_keypair, jwt_payload):
    priv, pub = rsa_keypair
    token = jwt.encode(jwt_payload, priv, algorithm="RS256")
    async with AsyncClient(transport=ASGITransport(app=production_app), base_url="http://test") as client:
        headers = {"authorization": f"Bearer {token}"}
        response = await client.post("/production/verify", json={"token": token}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["actor"] == jwt_payload["sub"]
        assert body["jti"] == jwt_payload["jti"]


@pytest.mark.asyncio
async def test_production_audit_endpoint_requires_auth(production_app):
    async with AsyncClient(transport=ASGITransport(app=production_app), base_url="http://test") as client:
        response = await client.get("/production/audit")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_production_replay_rejected(production_app, rsa_keypair, jwt_payload):
    priv, pub = rsa_keypair
    token = jwt.encode(jwt_payload, priv, algorithm="RS256")
    async with AsyncClient(transport=ASGITransport(app=production_app), base_url="http://test") as client:
        headers = {"authorization": f"Bearer {token}"}
        response1 = await client.get("/production/health", headers=headers)
        assert response1.status_code == 200
        response2 = await client.get("/production/health", headers=headers)
        assert response2.status_code == 403
        data = response2.json()
        assert data["error"]["type"] == "replay_error"


@pytest.mark.asyncio
async def test_production_unprotected_path_skips_middleware(production_app):
    async with AsyncClient(transport=ASGITransport(app=production_app), base_url="http://test") as client:
        response = await client.get("/unprotected")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# ProductionIdentity model
# ---------------------------------------------------------------------------

def test_production_identity_model():
    identity = ProductionIdentity(actor="a", roles=["admin"], jti="j")
    assert identity.actor == "a"
    with pytest.raises(ValueError):
        ProductionIdentity(actor="", roles=[], jti="j")
