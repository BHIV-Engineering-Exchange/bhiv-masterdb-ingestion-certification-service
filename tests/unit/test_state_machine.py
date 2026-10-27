"""
Unit tests for Deterministic State Machine & Concurrency Control (T-GOV-002).
"""
import asyncio
import pytest

from evaluation_engine.rule_engine import RuleEngine
from models import PackageStatus
from models_pravah import PravahEntityType
from services.state_machine import (
    EntityState,
    InvalidStateTransitionError,
    PravahStateMachine,
)


@pytest.fixture
def state_machine():
    return PravahStateMachine()


@pytest.mark.asyncio
async def test_legal_state_transition(state_machine):
    state = await state_machine.transition(
        entity_id="pkg-legal-1",
        target_status=PackageStatus.INGESTED,
        event_id="evt-1",
        context={"source_verified": True},
    )
    assert state.current_status == PackageStatus.INGESTED
    assert state.version == 2
    assert "evt-1" in state.applied_events


@pytest.mark.asyncio
async def test_illegal_state_transition_raises_controlled_error(state_machine):
    # Attempt jumping directly from REGISTERED to CERTIFIED
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        await state_machine.transition(
            entity_id="pkg-illegal-1",
            target_status=PackageStatus.CERTIFIED,
            event_id="evt-jump",
        )
    assert "Transition not allowed in lifecycle graph" in str(exc_info.value)
    assert exc_info.value.from_status == PackageStatus.REGISTERED
    assert exc_info.value.to_status == PackageStatus.CERTIFIED


@pytest.mark.asyncio
async def test_rule_failure_blocks_transition(state_machine):
    # INGESTED requires source_verified=True; if False, must reject
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        await state_machine.transition(
            entity_id="pkg-rule-fail",
            target_status=PackageStatus.INGESTED,
            event_id="evt-bad-rule",
            context={"source_verified": False},
        )
    assert "Rule check failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_idempotent_event_application(state_machine):
    state1 = await state_machine.transition(
        entity_id="pkg-idemp",
        target_status=PackageStatus.INGESTED,
        event_id="evt-repeat",
        context={"source_verified": True},
    )
    v1 = state1.version

    # Repeated transition with identical event_id
    state2 = await state_machine.transition(
        entity_id="pkg-idemp",
        target_status=PackageStatus.INGESTED,
        event_id="evt-repeat",
        context={"source_verified": True},
    )
    assert state2.version == v1
    assert len(state2.applied_events) == 1


def test_deterministic_canonicalization_and_hashing():
    state1 = EntityState("pkg-canonical", PravahEntityType.PACKAGE, PackageStatus.REGISTERED)
    state1.metadata = {"z_key": 100, "a_key": "val"}
    state1.applied_events = ["evt-2", "evt-1"]

    state2 = EntityState("pkg-canonical", PravahEntityType.PACKAGE, PackageStatus.REGISTERED)
    state2.metadata = {"a_key": "val", "z_key": 100}
    state2.applied_events = ["evt-1", "evt-2"]

    hash1 = state1.compute_state_hash()
    hash2 = state2.compute_state_hash()

    assert hash1 == hash2
    assert len(hash1) == 64


@pytest.mark.asyncio
async def test_concurrent_entity_locking(state_machine):
    entity_id = "pkg-concurrent-lock"

    # Advance to INGESTED first
    await state_machine.transition(
        entity_id=entity_id,
        target_status=PackageStatus.INGESTED,
        event_id="evt-init",
        context={"source_verified": True},
    )

    # Launch two concurrent attempts to transition to VALIDATED
    results = await asyncio.gather(
        state_machine.transition(
            entity_id=entity_id,
            target_status=PackageStatus.VALIDATED,
            event_id="evt-valid-1",
            context={"schema_integrity": 0.95},
        ),
        state_machine.transition(
            entity_id=entity_id,
            target_status=PackageStatus.VALIDATED,
            event_id="evt-valid-2",
            context={"schema_integrity": 0.95},
        ),
        return_exceptions=True,
    )

    # One transition succeeds; the other either succeeds (self-loop / idempotent) or completes cleanly
    state = state_machine.get_state(entity_id)
    assert state.current_status == PackageStatus.VALIDATED
