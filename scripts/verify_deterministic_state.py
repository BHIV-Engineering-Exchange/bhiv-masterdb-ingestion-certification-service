"""
Deterministic State Verification Script (T-GOV-002).

Executes 50 consecutive runs processing identical ordered event sequences
from identical initial states, verifying that 100% of the computed SHA-256
state hashes are identical.
"""
import asyncio
import sys
from pathlib import Path

# Ensure workspace root is in sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models import PackageStatus
from models_pravah import PravahEntityType, PravahEvent, PravahEventType
from services.event_pipeline import EventPipeline
from services.pravah_ledger import PravahReplayLedger
from services.state_machine import PravahStateMachine


def build_deterministic_event_sequence(entity_id: str) -> List[PravahEvent]:
    """
    Construct a fixed, deterministic sequence of Pravah events
    with explicit deterministic identifiers and test inputs.
    """
    return [
        PravahEvent(
            event_id=f"det-evt-01-{entity_id}",
            topic="pravah.masterdb.events",
            event_type=PravahEventType.INGESTION_REQUESTED,
            entity_type=PravahEntityType.PACKAGE,
            entity_id=entity_id,
            producer="test-runner",
            target_status=PackageStatus.INGESTED,
            payload={"source_verified": True, "source_id": "src-gov-fsi-001"},
        ),
        PravahEvent(
            event_id=f"det-evt-02-{entity_id}",
            topic="pravah.masterdb.events",
            event_type=PravahEventType.VALIDATION_COMPLETED,
            entity_type=PravahEntityType.PACKAGE,
            entity_id=entity_id,
            producer="test-runner",
            target_status=PackageStatus.VALIDATED,
            payload={"schema_integrity": 0.98, "rows": 15420},
        ),
        PravahEvent(
            event_id=f"det-evt-03-{entity_id}",
            topic="pravah.masterdb.events",
            event_type=PravahEventType.VERIFICATION_COMPLETED,
            entity_type=PravahEntityType.PACKAGE,
            entity_id=entity_id,
            producer="test-runner",
            target_status=PackageStatus.VERIFIED,
            payload={"compliance_verified": True, "authority": "BHIV-CENTRAL"},
        ),
        PravahEvent(
            event_id=f"det-evt-04-{entity_id}",
            topic="pravah.masterdb.events",
            event_type=PravahEventType.CERTIFICATION_GRANTED,
            entity_type=PravahEntityType.PACKAGE,
            entity_id=entity_id,
            producer="test-runner",
            target_status=PackageStatus.CERTIFIED,
            payload={"certification_score": 96.5, "certifier": "parikshak-gov"},
        ),
        PravahEvent(
            event_id=f"det-evt-05-{entity_id}",
            topic="pravah.masterdb.events",
            event_type=PravahEventType.STATUS_CHANGED,
            entity_type=PravahEntityType.PACKAGE,
            entity_id=entity_id,
            producer="test-runner",
            target_status=PackageStatus.RETRIEVAL_READY,
            payload={"contract_published": True, "access_tier": "ecosystem"},
        ),
    ]


async def run_single_deterministic_pass(pass_number: int, entity_id: str) -> str:
    """Execute a single run and return the resulting SHA-256 state hash."""
    ledger = PravahReplayLedger()
    state_machine = PravahStateMachine()
    pipeline = EventPipeline(ledger=ledger, state_machine=state_machine)

    events = build_deterministic_event_sequence(entity_id)
    for event in events:
        await pipeline.process_event(event)

    state = state_machine.get_state(entity_id)
    assert state is not None
    assert state.current_status == PackageStatus.RETRIEVAL_READY
    return state.compute_state_hash()


async def run_deterministic_verification(runs: int = 50, entity_id: str = "pkg-det-gov-002") -> Dict[str, Any]:
    """
    Run 50 consecutive deterministic executions and verify all SHA-256 state hashes match.
    """
    hashes: List[str] = []
    print(f"[*] Starting {runs} consecutive deterministic state hash runs for entity '{entity_id}'...")

    for i in range(1, runs + 1):
        state_hash = await run_single_deterministic_pass(i, entity_id)
        hashes.append(state_hash)

    first_hash = hashes[0]
    all_identical = all(h == first_hash for h in hashes)

    unique_hashes = set(hashes)
    status_str = "PASS" if (all_identical and len(unique_hashes) == 1) else "FAIL"

    print(f"[*] Completed {runs} runs. Status: {status_str}")
    print(f"[*] Canonical SHA-256 State Hash: {first_hash}")
    print(f"[*] Unique hashes observed: {len(unique_hashes)}")

    return {
        "runs_completed": runs,
        "identical_hashes": all_identical,
        "final_hash": first_hash,
        "unique_hash_count": len(unique_hashes),
        "hash_history": hashes,
        "status": status_str,
    }


def main():
    result = asyncio.run(run_deterministic_verification(runs=50))
    if not result["identical_hashes"]:
        print("FAIL: Hash mismatch detected across runs!", file=sys.stderr)
        sys.exit(1)
    print("SUCCESS: 50 consecutive executions produced 100% identical SHA-256 state hashes.")
    sys.exit(0)


if __name__ == "__main__":
    main()
