# CODE_INDEX.md — T-GOV-002 Milestone Advancement

**Task ID:** T-GOV-002
**Task Title:** Milestone Advancement: Scalable Ecosystem Integration & Pipeline Automation
**Candidate:** Kavy Changela
**Product Governance:** BHIV
**Date:** 2026-10-27

---

## 1. Directory Structure

```
masterdb-ingestion-certification-service/
├── main.py                              # FastAPI application root — wires all routers & services
├── models.py                            # Core domain models, PackageStatus, Lifecycle graph
├── models_pravah.py                     # [NEW] Strict Pydantic models for Pravah events, ledgers, pipeline
├── requirements.txt                     # Pinned direct dependencies (== exact versions)
│
├── api/
│   ├── production.py                    # Enterprise RS256 token verification & audit endpoints
│   └── pravah.py                        # [NEW] Pravah event ingestion, replay, state & determinism endpoints
│
├── evaluation_engine/
│   └── rule_engine.py                   # Pure, deterministic state transition rule evaluator
│
├── integrations/
│   ├── geospatial_connector.py          # Geospatial & VANA dataset connectors
│   ├── local_llm_client.py              # Local LLM client protected with CircuitBreaker
│   └── pravah_client.py                 # [NEW] Pravah event bus adapter with CircuitBreaker protection
│
├── middleware/
│   ├── circuit_breaker.py               # Three-state CircuitBreaker (CLOSED, OPEN, HALF_OPEN)
│   ├── rate_limit_middleware.py         # Sliding window rate-limiting middleware
│   └── rate_limiter.py                  # In-memory sliding window rate limiter
│
├── scripts/
│   └── verify_deterministic_state.py    # [NEW] 50-run deterministic state hash verification CLI & helper
│
├── security/
│   ├── middleware.py                    # RS256 JWT verifier, ReplayMitigationTable, SecurityMiddleware
│   └── path_resolution.py               # Path security & boundary sanitization
│
├── services/
│   ├── crypto_audit_emitter.py          # Immutable cryptographic SHA-256 chained audit emitter
│   ├── event_pipeline.py                # [NEW] Asynchronous event pipeline & multi-step orchestrator
│   ├── pravah_ledger.py                 # [NEW] Thread-safe append-only Pravah replay ledger
│   ├── state_machine.py                 # [NEW] Deterministic state machine with per-entity async locking
│   ├── startup_config.py                # One-time startup configuration validator & logger
│   ├── vana_client.py                   # VANA 6-tuple governance evaluation & spatial integration client
│   ├── mdu_client.py                    # Upstream MDU client
│   └── mdu_contract_adapter.py          # MDU schema & provenance contract adapter
│
├── task_selector/
│   └── review_orchestrator.py           # Coordinates RuleEngine, LLM, and audit emission
│
└── tests/
    ├── conftest.py                      # Session fixtures, autouse rate limiter reset, mock stores
    ├── unit/                            # [NEW] Unit test suite
    │   ├── test_pravah_models.py        # Event envelope, strict validation, forbidden extra fields
    │   ├── test_pravah_ledger.py        # Monotonic sequence, deduplication, queries, thread-safety
    │   └── test_state_machine.py        # Legal/illegal transitions, RuleEngine checks, entity locks
    │
    ├── integration/                     # [NEW] Integration test suite
    │   ├── test_event_pipeline.py       # End-to-end pipeline, replay idempotency, 50-run determinism
    │   ├── test_pravah_api.py           # HTTP endpoints, validation error boundaries (zero 500s)
    │   └── test_pravah_client.py        # Live & simulated dispatch, circuit breaker trips
    │
    ├── test_mdu_contract_adapter.py     # MDU contract negotiation & circuit breaker tests
    ├── test_persistence_security.py     # Production fail-closed persistence validation tests
    ├── test_vana_integration.py         # VANA governance, spatial layers & capability access tests
    └── ... (64 total regression test modules)
```

---

## 2. Core Modules & Responsibilities

| Module | Primary Responsibility |
|--------|------------------------|
| `models_pravah.py` | Defines immutable event envelopes, ledger entries, replay requests, determinism results, and pipeline schemas using strict Pydantic (`extra="forbid"`). |
| `services/pravah_ledger.py` | Append-only event log maintaining monotonically increasing sequence numbers, dual-index deduplication, and atomic snapshot persistence. |
| `services/state_machine.py` | Executes deterministic lifecycle transitions, validates lifecycle graph edges, evaluates RuleEngine rules, serializes canonical state, and computes SHA-256 state hashes. |
| `services/event_pipeline.py` | Asynchronous coordinator linking replay ledger, state machine, cryptographic audit chain, and downstream Pravah publisher. |
| `integrations/pravah_client.py` | Pravah event bus adapter with circuit-breaker resilience and deterministic simulated test-double mode. |
| `api/pravah.py` | REST API routes for `/pravah/events`, `/pravah/ledger`, `/pravah/replay`, `/pravah/state/{id}`, `/pravah/verify-determinism`, and `/pipeline/execute`. |
| `scripts/verify_deterministic_state.py` | Standalone CLI and programmatic test runner for 50-consecutive-run SHA-256 state hash determinism verification. |

---

## 3. Key Entry Points

- **Event Ingestion:** `POST /pravah/events` in `api/pravah.py` -> `EventPipeline.process_event()` in `services/event_pipeline.py`.
- **Replay Execution:** `POST /pravah/replay` in `api/pravah.py` -> `EventPipeline.replay_ledger()` in `services/event_pipeline.py`.
- **Pipeline Automation:** `POST /pipeline/execute` in `api/pravah.py` -> `EventPipeline.execute_pipeline()` in `services/event_pipeline.py`.
- **Deterministic Verification:** `python scripts/verify_deterministic_state.py` or `POST /pravah/verify-determinism`.
- **Application Startup:** `main.py` -> initializes all singletons, wires `pravah_router`, and adds uniform `RequestValidationError` handler.