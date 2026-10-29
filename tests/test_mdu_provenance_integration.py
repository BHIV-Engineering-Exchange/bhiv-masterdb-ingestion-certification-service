"""
Automated unit and mock tests for MDU authentication, provenance read/write,
relationship endpoints, and trace ID continuity.
"""
import httpx
import pytest

from services.mdu_client import MDUClient, MDUUnavailableError
from services.mdu_contract_adapter import MDUContractAdapter
from utils.trace import generate_trace_id, is_valid_trace_id, normalize_trace_id
from upload.models import UploadJob
from database_targets.models import IngestJob, IngestRequest, TargetDatabase, IngestionFormat
from database_targets.service import DatabaseRouterService
from services.artifact_store import ArtifactStore


class DummyResponse:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"Client error '{self.status_code}'", request=request, response=response
            )


def test_trace_id_utilities():
    tid = generate_trace_id()
    assert is_valid_trace_id(tid)
    assert len(tid) == 32

    # Normalization of hyphenated UUID
    uuid_str = "6f84dede-43f4-488d-8bb4-c17f712d7e1a"
    assert normalize_trace_id(uuid_str) == "6f84dede43f4488d8bb4c17f712d7e1a"

    # Normalization of legacy trace- prefix
    legacy = f"trace-{tid}"
    assert normalize_trace_id(legacy) == tid

    # None or invalid generates a fresh 32-hex
    fresh = normalize_trace_id(None)
    assert is_valid_trace_id(fresh)
    assert len(fresh) == 32


def test_mdu_client_unconfigured(monkeypatch):
    monkeypatch.delenv("MDU_BASE_URL", raising=False)
    monkeypatch.delenv("MDU_API_KEY", raising=False)
    client = MDUClient(base_url=None, api_key=None)

    assert not client.is_configured()
    with pytest.raises(MDUUnavailableError) as exc_info:
        client.get_discovery_summary()
    assert "not configured" in str(exc_info.value)

    with pytest.raises(MDUUnavailableError) as exc_info:
        client.record_provenance("uuid-123", {"event_type": "TEST"})
    assert "not configured" in str(exc_info.value)


def test_mdu_client_headers_and_trace_propagation(monkeypatch):
    captured_requests = []

    def mock_call(method, url, **kwargs):
        captured_requests.append((method, url, kwargs))
        return DummyResponse(200, {"status": "ok"})

    client = MDUClient(base_url="https://mdu.test", api_key="secret-api-key")
    monkeypatch.setattr(client._circuit_breaker, "call", mock_call)

    custom_trace = "0123456789abcdef0123456789abcdef"
    client.get_canonical_dataset("BHIV-DS-001", trace_id=custom_trace)

    assert len(captured_requests) == 1
    method, url, kwargs = captured_requests[0]
    assert method == httpx.get
    assert url == "https://mdu.test/api/v1/datasets/canonical/BHIV-DS-001"
    headers = kwargs["headers"]
    assert headers["X-API-Key"] == "secret-api-key"
    assert headers["X-Trace-Id"] == custom_trace


def test_mdu_client_post_provenance(monkeypatch):
    captured = []

    def mock_call(method, url, **kwargs):
        captured.append((method, url, kwargs))
        return DummyResponse(201, {"id": "prov-001", "event_type": "INGESTION"})

    client = MDUClient(base_url="https://mdu.test", api_key="secret-key")
    monkeypatch.setattr(client._circuit_breaker, "call", mock_call)

    payload = {
        "event_type": "INGESTION",
        "recorded_by": "MASTERDB",
        "source_system": "MASTERDB",
        "is_replay_safe": True,
    }
    dataset_uuid = "6f84dede-43f4-488d-8bb4-c17f712d7e1a"
    res = client.record_provenance(dataset_uuid, payload, trace_id="11112222333344445555666677778888")

    assert res["id"] == "prov-001"
    assert len(captured) == 1
    method, url, kwargs = captured[0]
    assert method == httpx.post
    assert url == f"https://mdu.test/api/v1/datasets/{dataset_uuid}/provenance"
    assert kwargs["json"] == payload
    assert kwargs["headers"]["X-Trace-Id"] == "11112222333344445555666677778888"


def test_mdu_client_create_relationship_and_read(monkeypatch):
    captured = []

    def mock_call(method, url, **kwargs):
        captured.append((method, url, kwargs))
        if method == httpx.post:
            return DummyResponse(201, {"id": "rel-001", "relationship_type": "DERIVED_FROM"})
        return DummyResponse(200, [{"id": "rel-001", "relationship_type": "DERIVED_FROM"}])

    client = MDUClient(base_url="https://mdu.test", api_key="secret-key")
    monkeypatch.setattr(client._circuit_breaker, "call", mock_call)

    rel_payload = {
        "parent_dataset_id": "parent-uuid",
        "child_dataset_id": "child-uuid",
        "relationship_type": "DERIVED_FROM",
        "created_by": "MASTERDB",
    }
    create_res = client.create_relationship(rel_payload)
    assert create_res["id"] == "rel-001"

    read_res = client.get_dataset_relationships("child-uuid")
    assert isinstance(read_res, list)
    assert read_res[0]["id"] == "rel-001"


def test_mdu_client_auth_failure_sanitization(monkeypatch):
    client = MDUClient(base_url="https://mdu.test", api_key="super-secret-mdu-key")

    def mock_call_401(*args, **kwargs):
        return DummyResponse(401, {"detail": "Invalid API key"})

    monkeypatch.setattr(client._circuit_breaker, "call", mock_call_401)

    with pytest.raises(MDUUnavailableError) as exc_info:
        client.get_discovery_summary()

    err_msg = str(exc_info.value)
    assert "HTTP 401 Unauthorized" in err_msg
    assert "super-secret-mdu-key" not in err_msg


def test_mdu_client_forbidden_sanitization(monkeypatch):
    client = MDUClient(base_url="https://mdu.test", api_key="super-secret-mdu-key")

    def mock_call_403(*args, **kwargs):
        return DummyResponse(403, {"detail": "Forbidden"})

    monkeypatch.setattr(client._circuit_breaker, "call", mock_call_403)

    with pytest.raises(MDUUnavailableError) as exc_info:
        client.get_dataset_schema("some-id")

    err_msg = str(exc_info.value)
    assert "HTTP 403 Forbidden" in err_msg
    assert "super-secret-mdu-key" not in err_msg


def test_adapter_record_provenance_event_resolves_id(monkeypatch):
    client = MDUClient(base_url="https://mdu.test", api_key="test-key")
    adapter = MDUContractAdapter(client=client)

    # Mock canonical lookup
    monkeypatch.setattr(
        client,
        "get_canonical_dataset",
        lambda cid, trace_id=None: {"id": "resolved-uuid-456", "canonical_id": cid},
    )

    recorded_payload = []

    def mock_record_prov(dataset_id, payload, trace_id=None):
        recorded_payload.append((dataset_id, payload, trace_id))
        return {"id": "prov-123", "dataset_id": dataset_id, **payload}

    monkeypatch.setattr(client, "record_provenance", mock_record_prov)

    custom_trace = "abcdef0123456789abcdef0123456789"
    result = adapter.record_provenance_event(
        dataset_id="BHIV-DS-MARITIME-AIS-LIVE-001",
        event_type="INGESTION",
        recorded_by="MASTERDB",
        notes="Automated test event",
        trace_id=custom_trace,
    )

    assert result["id"] == "prov-123"
    assert len(recorded_payload) == 1
    dataset_id, payload, trace_id = recorded_payload[0]
    assert dataset_id == "resolved-uuid-456"
    assert payload["event_type"] == "INGESTION"
    assert payload["notes"] == "Automated test event"
    assert trace_id == custom_trace


def test_adapter_create_dataset_relationship_resolves_ids(monkeypatch):
    client = MDUClient(base_url="https://mdu.test", api_key="test-key")
    adapter = MDUContractAdapter(client=client)

    def mock_canonical(cid, trace_id=None):
        if cid == "BHIV-PARENT":
            return {"id": "uuid-parent"}
        if cid == "BHIV-CHILD":
            return {"id": "uuid-child"}
        return {"id": "uuid-unknown"}

    monkeypatch.setattr(client, "get_canonical_dataset", mock_canonical)

    recorded_rel = []

    def mock_create_rel(payload, trace_id=None):
        recorded_rel.append((payload, trace_id))
        return {"id": "rel-999", **payload}

    monkeypatch.setattr(client, "create_relationship", mock_create_rel)

    result = adapter.create_dataset_relationship(
        parent_dataset_id="BHIV-PARENT",
        child_dataset_id="BHIV-CHILD",
        relationship_type="DERIVED_FROM",
    )

    assert result["id"] == "rel-999"
    assert len(recorded_rel) == 1
    payload, _ = recorded_rel[0]
    assert payload["parent_dataset_id"] == "uuid-parent"
    assert payload["child_dataset_id"] == "uuid-child"
    assert payload["relationship_type"] == "DERIVED_FROM"


def test_ingest_preserves_upload_trace_id(tmp_path):
    cert_store = ArtifactStore(reports_dir=str(tmp_path / "cert_store"))
    # Save a fake certified report
    dataset_id = "test-dataset-01"
    cert_store.save(dataset_id, {
        "state": "CERTIFIED",
        "ingestion_decision": {"eligible_for_masterdb": True},
        "integrity_score": 100.0,
    })

    class FakeUpload:
        def __init__(self, trace_id):
            self.upload_id = "upl-test-123"
            self.trace_id = trace_id
            self.storage_path = None
            self.dataset_id = dataset_id

    class FakeUploadService:
        def get_upload(self, upload_id):
            return FakeUpload("1234567890abcdef1234567890abcdef")

        def link_ingestion_job(self, upload_id, job_id):
            pass

    class FakeTargetStore:
        def persist_target_dataset(self, **kwargs):
            return {"record_count": 10, "target_reference": "VectorDB/test-dataset-01"}

    service = DatabaseRouterService(
        certification_artifact_store=cert_store,
        store_dir=str(tmp_path / "job_store"),
        target_store=FakeTargetStore(),
        upload_service=FakeUploadService(),
    )
    # Mock records resolution
    monkeypatch_records = lambda *args, **kwargs: [{"id": 1}]
    service._resolve_dataset_records = monkeypatch_records

    # Ingest referencing upload_id
    job = service.ingest(
        dataset_id=dataset_id,
        target_database=TargetDatabase.VECTOR_DB,
        source_format=IngestionFormat.JSON,
        actor="admin_user",
        roles=["vector_operator"],
        upload_id="upl-test-123",
    )

    # Verified trace_id continuity from the linked upload!
    assert job.trace_id == "1234567890abcdef1234567890abcdef"


def test_ingest_idempotency_identical_retry(tmp_path):
    cert_store = ArtifactStore(reports_dir=str(tmp_path / "cert_store"))
    dataset_id = "test-dataset-idem-01"
    cert_store.save(dataset_id, {
        "state": "CERTIFIED",
        "ingestion_decision": {"eligible_for_masterdb": True},
        "integrity_score": 100.0,
    })

    class FakeTargetStore:
        def __init__(self):
            self.persist_count = 0

        def persist_target_dataset(self, **kwargs):
            self.persist_count += 1
            return {"record_count": 5, "target_reference": f"VectorDB/{dataset_id}"}

    target_store = FakeTargetStore()
    service = DatabaseRouterService(
        certification_artifact_store=cert_store,
        store_dir=str(tmp_path / "job_store"),
        target_store=target_store,
    )
    service._resolve_dataset_records = lambda *args, **kwargs: [{"id": 1}]

    # First ingest call
    job1 = service.ingest(
        dataset_id=dataset_id,
        target_database=TargetDatabase.VECTOR_DB,
        source_format=IngestionFormat.JSON,
        actor="admin_user",
        roles=["ingest:vectordb"],
        idempotency_key="idem-key-12345",
    )

    assert job1.idempotency_key == "idem-key-12345"
    assert target_store.persist_count == 1

    # Second identical ingest call with same idempotency key
    job2 = service.ingest(
        dataset_id=dataset_id,
        target_database=TargetDatabase.VECTOR_DB,
        source_format=IngestionFormat.JSON,
        actor="admin_user",
        roles=["ingest:vectordb"],
        idempotency_key="idem-key-12345",
    )

    # Identical job returned, persistence NOT duplicated!
    assert job2.job_id == job1.job_id
    assert job2.trace_id == job1.trace_id
    assert job2.idempotency_key == "idem-key-12345"
    assert target_store.persist_count == 1


def test_ingest_idempotency_conflict_raises(tmp_path):
    from database_targets.models import IdempotencyConflictError

    cert_store = ArtifactStore(reports_dir=str(tmp_path / "cert_store"))
    cert_store.save("ds-A", {"state": "CERTIFIED", "ingestion_decision": {"eligible_for_masterdb": True}})
    cert_store.save("ds-B", {"state": "CERTIFIED", "ingestion_decision": {"eligible_for_masterdb": True}})

    class FakeTargetStore:
        def persist_target_dataset(self, **kwargs):
            return {"record_count": 5, "target_reference": "ref"}

    service = DatabaseRouterService(
        certification_artifact_store=cert_store,
        store_dir=str(tmp_path / "job_store"),
        target_store=FakeTargetStore(),
    )
    service._resolve_dataset_records = lambda *args, **kwargs: [{"id": 1}]

    service.ingest(
        dataset_id="ds-A",
        target_database=TargetDatabase.VECTOR_DB,
        source_format=IngestionFormat.JSON,
        actor="admin_user",
        roles=["ingest:vectordb"],
        idempotency_key="idem-conflict-key",
    )

    # Reusing same key with conflicting dataset_id must raise IdempotencyConflictError
    with pytest.raises(IdempotencyConflictError) as exc_info:
        service.ingest(
            dataset_id="ds-B",
            target_database=TargetDatabase.VECTOR_DB,
            source_format=IngestionFormat.JSON,
            actor="admin_user",
            roles=["ingest:vectordb"],
            idempotency_key="idem-conflict-key",
        )
    assert "conflict" in str(exc_info.value).lower()


def test_ingest_idempotency_distinct_keys(tmp_path):
    cert_store = ArtifactStore(reports_dir=str(tmp_path / "cert_store"))
    dataset_id = "test-dataset-distinct"
    cert_store.save(dataset_id, {"state": "CERTIFIED", "ingestion_decision": {"eligible_for_masterdb": True}})

    class FakeTargetStore:
        def persist_target_dataset(self, **kwargs):
            return {"record_count": 5, "target_reference": f"VectorDB/{dataset_id}"}

    service = DatabaseRouterService(
        certification_artifact_store=cert_store,
        store_dir=str(tmp_path / "job_store"),
        target_store=FakeTargetStore(),
    )
    service._resolve_dataset_records = lambda *args, **kwargs: [{"id": 1}]

    job1 = service.ingest(
        dataset_id=dataset_id,
        target_database=TargetDatabase.VECTOR_DB,
        source_format=IngestionFormat.JSON,
        actor="admin_user",
        roles=["ingest:vectordb"],
        idempotency_key="key-A",
    )
    job2 = service.ingest(
        dataset_id=dataset_id,
        target_database=TargetDatabase.VECTOR_DB,
        source_format=IngestionFormat.JSON,
        actor="admin_user",
        roles=["ingest:vectordb"],
        idempotency_key="key-B",
    )

    assert job1.job_id != job2.job_id
    assert job1.idempotency_key == "key-A"
    assert job2.idempotency_key == "key-B"


def test_ingest_idempotency_concurrency(tmp_path):
    import concurrent.futures

    cert_store = ArtifactStore(reports_dir=str(tmp_path / "cert_store"))
    dataset_id = "test-dataset-concurrent"
    cert_store.save(dataset_id, {"state": "CERTIFIED", "ingestion_decision": {"eligible_for_masterdb": True}})

    class FakeTargetStore:
        def persist_target_dataset(self, **kwargs):
            return {"record_count": 5, "target_reference": f"VectorDB/{dataset_id}"}

    service = DatabaseRouterService(
        certification_artifact_store=cert_store,
        store_dir=str(tmp_path / "job_store"),
        target_store=FakeTargetStore(),
    )
    service._resolve_dataset_records = lambda *args, **kwargs: [{"id": 1}]

    def do_ingest():
        return service.ingest(
            dataset_id=dataset_id,
            target_database=TargetDatabase.VECTOR_DB,
            source_format=IngestionFormat.JSON,
            actor="admin_user",
            roles=["ingest:vectordb"],
            idempotency_key="concurrent-shared-key",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(do_ingest) for _ in range(5)]
        jobs = [f.result() for f in futures]

    # All concurrent threads must return the exact same job ID
    job_ids = {j.job_id for j in jobs}
    assert len(job_ids) == 1

