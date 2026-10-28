"""
Unit tests for Pravah Replay Ledger (T-GOV-002).
"""
import concurrent.futures
from pathlib import Path

import pytest

from models import PackageStatus
from models_pravah import (
    PravahEntityType,
    PravahEvent,
    PravahEventStatus,
    PravahEventType,
)
from services.pravah_ledger import PravahReplayLedger


@pytest.fixture
def clean_ledger():
    ledger = PravahReplayLedger()
    ledger.clear()
    yield ledger
    ledger.clear()


def test_monotonic_sequence_numbering(clean_ledger):
    for i in range(1, 6):
        event = PravahEvent(
            event_id=f"evt-{i}",
            event_type=PravahEventType.INGESTION_REQUESTED,
            entity_id=f"pkg-{i}",
        )
        entry = clean_ledger.record_event(event)
        assert entry.sequence_number == i
    assert clean_ledger.total_count() == 5


def test_event_id_deduplication(clean_ledger):
    event1 = PravahEvent(
        event_id="evt-dup-1",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_id="pkg-1",
    )
    entry1 = clean_ledger.record_event(event1)
    assert entry1.sequence_number == 1

    # Attempt to record identical event_id
    event2 = PravahEvent(
        event_id="evt-dup-1",
        event_type=PravahEventType.VALIDATION_COMPLETED,
        entity_id="pkg-1",
    )
    entry2 = clean_ledger.record_event(event2)
    assert entry2.sequence_number == 1
    assert clean_ledger.total_count() == 1


def test_idempotency_key_deduplication(clean_ledger):
    event1 = PravahEvent(
        event_id="evt-a",
        idempotency_key="idemp-key-999",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_id="pkg-1",
    )
    entry1 = clean_ledger.record_event(event1)
    assert entry1.sequence_number == 1

    event2 = PravahEvent(
        event_id="evt-b",
        idempotency_key="idemp-key-999",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_id="pkg-1",
    )
    entry2 = clean_ledger.record_event(event2)
    assert entry2.sequence_number == 1
    assert clean_ledger.total_count() == 1


def test_commit_and_fail_entry(clean_ledger):
    event = PravahEvent(
        event_id="evt-state",
        event_type=PravahEventType.VALIDATION_COMPLETED,
        entity_id="pkg-1",
    )
    entry = clean_ledger.record_event(event)
    assert entry.status == PravahEventStatus.PENDING

    # Commit with hash
    committed = clean_ledger.commit_entry(entry.sequence_number, state_hash_after="deadbeef1234")
    assert committed.status == PravahEventStatus.COMMITTED
    assert committed.state_hash_after == "deadbeef1234"
    assert committed.processed_at is not None

    # Fail entry
    failed = clean_ledger.fail_entry(entry.sequence_number, error_message="Rule check failed")
    assert failed.status == PravahEventStatus.FAILED
    assert failed.error_message == "Rule check failed"
    assert failed.retry_count == 1


def test_query_and_filter_entries(clean_ledger):
    clean_ledger.record_event(
        PravahEvent(
            event_id="e1",
            topic="topic-A",
            event_type=PravahEventType.INGESTION_REQUESTED,
            entity_id="pkg-1",
        )
    )
    clean_ledger.record_event(
        PravahEvent(
            event_id="e2",
            topic="topic-B",
            event_type=PravahEventType.VALIDATION_COMPLETED,
            entity_id="pkg-2",
        )
    )
    clean_ledger.record_event(
        PravahEvent(
            event_id="e3",
            topic="topic-A",
            event_type=PravahEventType.VERIFICATION_COMPLETED,
            entity_id="pkg-1",
        )
    )

    topic_a = clean_ledger.query_entries(topic="topic-A")
    assert len(topic_a) == 2

    pkg_2 = clean_ledger.query_entries(entity_id="pkg-2")
    assert len(pkg_2) == 1
    assert pkg_2[0].event.event_id == "e2"


def test_snapshot_persistence_and_recovery(tmp_path):
    snap_file = str(tmp_path / "ledger_snapshot.json")
    ledger1 = PravahReplayLedger(persistence_path=snap_file)

    for i in range(1, 4):
        ledger1.record_event(
            PravahEvent(
                event_id=f"snap-evt-{i}",
                event_type=PravahEventType.INGESTION_REQUESTED,
                entity_id=f"pkg-{i}",
            )
        )
    assert ledger1.total_count() == 3

    # Create new instance pointing to same file
    ledger2 = PravahReplayLedger(persistence_path=snap_file)
    assert ledger2.total_count() == 3
    assert ledger2.get_entry(2).event.event_id == "snap-evt-2"


def test_concurrent_recording_integrity(clean_ledger):
    num_threads = 10
    events_per_thread = 20

    def record_batch(thread_id: int):
        for j in range(events_per_thread):
            clean_ledger.record_event(
                PravahEvent(
                    event_id=f"th-{thread_id}-evt-{j}",
                    event_type=PravahEventType.STATUS_CHANGED,
                    entity_id=f"pkg-concurrent-{thread_id}",
                )
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(record_batch, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)

    assert clean_ledger.total_count() == num_threads * events_per_thread
    # Ensure all sequence numbers from 1 to total_count exist and are strictly ordered
    seqs = [e.sequence_number for e in clean_ledger.query_entries(limit=1000)]
    assert seqs == list(range(1, (num_threads * events_per_thread) + 1))
