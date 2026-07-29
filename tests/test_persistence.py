"""
Proves persist_dir actually persists — not just that passing it doesn't
crash. Each test creates a service against a temp directory, writes data,
throws the service instance away, creates a *new* service instance against
the same directory, and checks the data is there. That's the real test of
"survives a restart," since main.py's process restarting is exactly
"old Python objects gone, new ones constructed against the same directory."
"""
import shutil
import tempfile

import pytest

from bcaes_registry.models import RegisterObjectRequest, RegistryType
from bcaes_registry.service import BCAESRegistryService
from canonical_repository.models import DocumentCategory, PublishVersionRequest, RegisterDocumentRequest
from canonical_repository.service import CanonicalRepositoryService


@pytest.fixture
def tmp_dir():
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_bcaes_registry_default_is_pure_in_memory_no_disk_touched(tmp_path, monkeypatch):
    """Sanity check for the default (no persist_dir): nothing is written
    to the process's actual working directory."""
    monkeypatch.chdir(tmp_path)
    service = BCAESRegistryService()
    service.register(
        RegistryType.CAPABILITY,
        RegisterObjectRequest(name="X", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )
    assert not (tmp_path / "storage").exists()
    assert not any(tmp_path.iterdir())


def test_bcaes_registry_persists_across_a_fresh_instance(tmp_dir):
    service_a = BCAESRegistryService(persist_dir=tmp_dir)
    obj = service_a.register(
        RegistryType.CAPABILITY,
        RegisterObjectRequest(name="Schema Validation", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )

    # Simulate a process restart: throw away service_a, build a fresh one
    # against the same directory.
    service_b = BCAESRegistryService(persist_dir=tmp_dir)
    reloaded = service_b.get(RegistryType.CAPABILITY, obj.id)
    assert reloaded.name == "Schema Validation"
    assert reloaded.owner == "Kavy"


def test_bcaes_registry_update_persists(tmp_dir):
    service_a = BCAESRegistryService(persist_dir=tmp_dir)
    obj = service_a.register(
        RegistryType.ENGINE,
        RegisterObjectRequest(name="Scoring Engine", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )
    from bcaes_registry.models import UpdateObjectRequest
    service_a.update(RegistryType.ENGINE, obj.id, UpdateObjectRequest(version="2.0"))

    service_b = BCAESRegistryService(persist_dir=tmp_dir)
    reloaded = service_b.get(RegistryType.ENGINE, obj.id)
    assert reloaded.version == "2.0"


def test_bcaes_registry_delete_persists(tmp_dir):
    service_a = BCAESRegistryService(persist_dir=tmp_dir)
    obj = service_a.register(
        RegistryType.FRAMEWORK,
        RegisterObjectRequest(name="Retry Framework", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )
    service_a.delete(RegistryType.FRAMEWORK, obj.id)

    service_b = BCAESRegistryService(persist_dir=tmp_dir)
    from bcaes_registry.store import ObjectNotFoundError
    with pytest.raises(ObjectNotFoundError):
        service_b.get(RegistryType.FRAMEWORK, obj.id)


def test_canonical_repository_persists_document_and_versions_across_fresh_instance(tmp_dir):
    service_a = CanonicalRepositoryService(persist_dir=tmp_dir)
    doc = service_a.register(
        RegisterDocumentRequest(category=DocumentCategory.BCAES_VOL_4, title="Vol 4", owner="Kavy"),
        actor="Kavy",
        actor_roles=["bcaes-editor"],
    )
    service_a.publish_version(
        doc.id,
        PublishVersionRequest(content="real content", change_note="n", published_by="Kavy"),
        actor="Kavy",
        actor_roles=["bcaes-editor"],
    )

    service_b = CanonicalRepositoryService(persist_dir=tmp_dir)
    reloaded = service_b.get(doc.id, actor="Kavy", actor_roles=["ecosystem-reader"])
    assert reloaded.current_version == 2
    latest = service_b.latest_version(doc.id, actor="Kavy", actor_roles=["ecosystem-reader"])
    assert latest.content == "real content"
    history = service_b.version_history(doc.id, actor="Kavy", actor_roles=["ecosystem-reader"])
    assert len(history) == 2


def test_canonical_repository_default_is_pure_in_memory_no_disk_touched(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = CanonicalRepositoryService()
    service.register(
        RegisterDocumentRequest(category=DocumentCategory.BCAB, title="BCAB", owner="Kavy"),
        actor="Kavy",
        actor_roles=["bcaes-editor"],
    )
    assert not any(tmp_path.iterdir())
