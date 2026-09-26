"""Unit tests for MASTERDB Upload Service (MASTERDB-BE-02)."""
import os
import tempfile
from pathlib import Path

import pytest

from upload.models import UploadJob, UploadStatus, UploadJobStep
from upload.service import UploadService, UploadValidationError, UploadStateError
from upload.store import UploadStore


@pytest.fixture
def temp_staging_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def upload_store(temp_staging_dir):
    return UploadStore(store_dir=os.path.join(temp_staging_dir, 'upload_store'))


@pytest.fixture
def upload_service(upload_store, temp_staging_dir):
    return UploadService(store=upload_store, staging_dir=os.path.join(temp_staging_dir, 'staging'))


# Upload Initiation Tests

class TestUploadServiceInitiation:
    def test_initiate_upload_creates_job(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=1024,
            actor='test-user', roles=['admin'])
        assert job is not None
        assert job.upload_id.startswith('upl-')
        assert job.filename == 'test.csv'
        assert job.content_type == 'text/csv'
        assert job.file_size == 1024
        assert job.status == UploadStatus.UPLOADED
        assert job.actor == 'test-user'
        assert len(job.steps) == 1
        assert job.steps[0].step == 'UPLOAD_INITIATED'

    def test_initiate_upload_with_all_fields(self, upload_service):
        job = upload_service.initiate_upload(
            filename='dataset.xlsx',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            file_size=2048, actor='data-engineer', roles=['engineer'],
            checksum_sha256='e3b0c44298fc1c149afbf4c8996fb924',
            classification='internal', source_reference='FIN/VANA',
            provenance_metadata={'origin': 'system-a'}, schema_version='1.0.0',
            product_source='FIN/VANA', intended_use='analytics')
        assert job.classification == 'internal'
        assert job.source_reference == 'FIN/VANA'
        assert job.schema_version == '1.0.0'
        assert job.product_source == 'FIN/VANA'

    def test_initiate_upload_invalid_content_type(self, upload_service):
        with pytest.raises(UploadValidationError) as exc:
            upload_service.initiate_upload(
                filename='test.exe', content_type='application/x-executable',
                file_size=1024, actor='test-user', roles=[])
        assert 'not allowed' in str(exc.value)

    def test_initiate_upload_file_size_exceeds_limit(self, upload_service):
        with pytest.raises(UploadValidationError) as exc:
            upload_service.initiate_upload(
                filename='large.csv', content_type='text/csv',
                file_size=1 * 1024 * 1024 * 1024,
                actor='test-user', roles=[])
        assert 'exceeds' in str(exc.value)

    def test_initiate_upload_empty_filename(self, upload_service):
        with pytest.raises(UploadValidationError) as exc:
            upload_service.initiate_upload(
                filename='', content_type='text/csv', file_size=1024,
                actor='test-user', roles=[])
        assert 'cannot be empty' in str(exc.value)

    def test_initiate_upload_path_traversal(self, upload_service):
        with pytest.raises(UploadValidationError) as exc:
            upload_service.initiate_upload(
                filename='../../../etc/passwd', content_type='text/csv',
                file_size=1024, actor='test-user', roles=[])
        assert 'Invalid path characters' in str(exc.value)


class TestUploadReceive:
    def test_receive_upload_stages_file(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        content = b'hello'
        received_job = upload_service.receive_upload(job.upload_id, content)
        assert received_job.status == UploadStatus.RECEIVED
        assert received_job.received_at is not None
        assert received_job.storage_path is not None
        assert Path(received_job.storage_path).exists()

    def test_receive_upload_size_mismatch(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=100,
            actor='test-user', roles=[])
        with pytest.raises(UploadValidationError) as exc:
            upload_service.receive_upload(job.upload_id, b'short')
        assert 'Size mismatch' in str(exc.value)

    def test_receive_upload_invalid_state(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        upload_service.receive_upload(job.upload_id, b'hello')
        with pytest.raises(UploadStateError):
            upload_service.receive_upload(job.upload_id, b'hello')


class TestUploadValidation:
    def test_validate_upload_success(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        upload_service.receive_upload(job.upload_id, b'hello')
        validated_job = upload_service.validate_upload(job.upload_id)
        assert validated_job.status == UploadStatus.VALIDATED
        assert validated_job.validated_at is not None

    def test_validate_upload_with_checksum(self, upload_service):
        import hashlib
        content = b'hello'
        checksum = hashlib.sha256(content).hexdigest()
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[], checksum_sha256=checksum)
        upload_service.receive_upload(job.upload_id, content)
        validated_job = upload_service.validate_upload(job.upload_id)
        assert validated_job.status == UploadStatus.VALIDATED

    def test_validate_upload_checksum_mismatch(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[], checksum_sha256='a' * 64)
        upload_service.receive_upload(job.upload_id, b'hello')
        validated_job = upload_service.validate_upload(job.upload_id)
        assert validated_job.status == UploadStatus.REJECTED
        assert 'Checksum mismatch' in validated_job.rejection_reason

    def test_validate_upload_missing_file(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        upload_service.receive_upload(job.upload_id, b'hello')
        # Remove staged file to simulate missing file at validation time
        os.remove(job.storage_path)
        validated_job = upload_service.validate_upload(job.upload_id)
        assert validated_job.status == UploadStatus.REJECTED
        assert 'not found' in validated_job.rejection_reason


class TestUploadLifecycle:
    def test_cancel_upload(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        cancelled_job = upload_service.cancel_upload(job.upload_id, 'User requested cancellation')
        assert cancelled_job.status == UploadStatus.REJECTED
        assert 'Cancelled' in cancelled_job.rejection_reason

    def test_cancel_upload_cleaned_up_staging(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        upload_service.receive_upload(job.upload_id, b'hello')
        assert Path(job.storage_path).exists()
        upload_service.cancel_upload(job.upload_id, 'cleanup')
        assert not Path(job.storage_path).exists()

    def test_register_dataset_after_validation(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        upload_service.receive_upload(job.upload_id, b'hello')
        upload_service.validate_upload(job.upload_id)
        registered_job = upload_service.register_dataset(
            job.upload_id, dataset_id='ds-001', package_id='pkg-001')
        assert registered_job.status == UploadStatus.REGISTERED
        assert registered_job.dataset_id == 'ds-001'

    def test_mark_ingested_after_registration(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        upload_service.receive_upload(job.upload_id, b'hello')
        upload_service.validate_upload(job.upload_id)
        upload_service.register_dataset(job.upload_id, dataset_id='ds-001', package_id='pkg-001')
        ingested_job = upload_service.mark_ingested(job.upload_id, artifact_id='art-001')
        assert ingested_job.status == UploadStatus.INGESTED
        assert ingested_job.artifact_id == 'art-001'

    def test_mark_available_after_ingested(self, upload_service):
        job = upload_service.initiate_upload(
            filename='test.csv', content_type='text/csv', file_size=5,
            actor='test-user', roles=[])
        upload_service.receive_upload(job.upload_id, b'hello')
        upload_service.validate_upload(job.upload_id)
        upload_service.register_dataset(job.upload_id, dataset_id='ds-001', package_id='pkg-001')
        upload_service.mark_ingested(job.upload_id, artifact_id='art-001')
        available_job = upload_service.mark_available(job.upload_id)
        assert available_job.status == UploadStatus.AVAILABLE


class TestUploadStore:
    def test_store_and_load_upload(self, upload_store):
        job = UploadJob(filename='test.csv', content_type='text/csv', file_size=100, actor='user', roles=[])
        upload_store.save(job)
        loaded = upload_store.load(job.upload_id)
        assert loaded is not None
        assert loaded.upload_id == job.upload_id
        assert loaded.filename == 'test.csv'

    def test_load_nonexistent_upload(self, upload_store):
        result = upload_store.load('nonexistent-id')
        assert result is None

    def test_list_all_uploads(self, upload_store):
        for i in range(3):
            job = UploadJob(filename=f'test{i}.csv', content_type='text/csv', file_size=100, actor='user', roles=[])
            upload_store.save(job)
        jobs = upload_store.list_all()
        assert len(jobs) == 3

    def test_list_uploads_filtered_by_status(self, upload_store):
        job1 = UploadJob(filename='test1.csv', content_type='text/csv', file_size=100, actor='user1', roles=[])
        job2 = UploadJob(filename='test2.csv', content_type='text/csv', file_size=100, actor='user1', roles=[])
        job1.status = UploadStatus.UPLOADED
        job2.status = UploadStatus.VALIDATED
        upload_store.save(job1)
        upload_store.save(job2)
        uploaded = upload_store.list_all(status=UploadStatus.UPLOADED)
        assert len(uploaded) == 1

    def test_delete_upload(self, upload_store):
        job = UploadJob(filename='test.csv', content_type='text/csv', file_size=100, actor='user', roles=[])
        upload_store.save(job)
        assert upload_store.exists(job.upload_id)
        upload_store.delete(job.upload_id)
        assert not upload_store.exists(job.upload_id)


class TestUploadModels:
    def test_upload_status_enum(self):
        assert UploadStatus.UPLOADED.value == 'UPLOADED'
        assert UploadStatus.RECEIVED.value == 'RECEIVED'
        assert UploadStatus.VALIDATING.value == 'VALIDATING'
        assert UploadStatus.VALIDATED.value == 'VALIDATED'
        assert UploadStatus.REJECTED.value == 'REJECTED'
        assert UploadStatus.REGISTERED.value == 'REGISTERED'
        assert UploadStatus.INGESTED.value == 'INGESTED'
        assert UploadStatus.AVAILABLE.value == 'AVAILABLE'

    def test_upload_job_step_model(self):
        step = UploadJobStep(step='TEST', passed=True, detail='Test step')
        assert step.step == 'TEST'
        assert step.passed is True
        assert step.detail == 'Test step'

    def test_upload_job_model_defaults(self):
        job = UploadJob(filename='test.csv', content_type='text/csv', file_size=100, actor='user', roles=[])
        assert job.upload_id.startswith('upl-')
        assert job.trace_id.startswith('trace-')
        assert job.status == UploadStatus.UPLOADED