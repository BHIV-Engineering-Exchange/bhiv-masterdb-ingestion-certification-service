import pytest

from bcaes_registry.models import (
    DependencyRef,
    ObjectStatus,
    RegisterObjectRequest,
    RegistryType,
    UpdateObjectRequest,
)
from bcaes_registry.service import BCAESRegistryService, DependencyNotFoundError, ObjectNotFoundError


@pytest.fixture
def service() -> BCAESRegistryService:
    svc = BCAESRegistryService()
    orig_reg = svc.register
    orig_upd = svc.update
    orig_del = svc.delete
    svc.register = lambda rt, req, actor="Kavy", actor_roles=None: orig_reg(rt, req, actor=actor, actor_roles=actor_roles or ["bhiv-admin"])
    svc.update = lambda rt, oid, req, actor="Kavy", actor_roles=None: orig_upd(rt, oid, req, actor=actor, actor_roles=actor_roles or ["bhiv-admin"])
    svc.delete = lambda rt, oid, actor="Kavy", actor_roles=None: orig_del(rt, oid, actor=actor, actor_roles=actor_roles or ["bhiv-admin"])
    return svc


def _req(name="Ingestion Certification", owner="Kavy", **overrides) -> RegisterObjectRequest:
    defaults = dict(
        name=name,
        purpose="Certifies datasets before ingestion.",
        owner=owner,
        authority_boundaries=[owner],
    )
    defaults.update(overrides)
    return RegisterObjectRequest(**defaults)


class TestRegistrationAndLookup:
    def test_register_assigns_prefixed_id_and_classification(self, service):
        obj = service.register(RegistryType.CAPABILITY, _req())
        assert obj.id.startswith("cap-")
        assert obj.registry_type == RegistryType.CAPABILITY
        assert obj.classification == RegistryType.CAPABILITY

    def test_get_roundtrip(self, service):
        obj = service.register(RegistryType.DOMAIN, _req(name="Knowledge Domain"))
        fetched = service.get(RegistryType.DOMAIN, obj.id)
        assert fetched.id == obj.id
        assert fetched.name == "Knowledge Domain"

    def test_get_missing_object_raises(self, service):
        with pytest.raises(ObjectNotFoundError):
            service.get(RegistryType.DOMAIN, "dom-doesnotexist")

    def test_each_registry_type_is_isolated(self, service):
        service.register(RegistryType.DOMAIN, _req(name="Same Name"))
        service.register(RegistryType.CAPABILITY, _req(name="Same Name"))
        summary = service.registry_summary()
        assert summary["domain"] == 1
        assert summary["capability"] == 1
        assert summary["product"] == 0


class TestDependenciesAndConsumers:
    def test_dependency_must_exist_at_registration(self, service):
        with pytest.raises(DependencyNotFoundError):
            service.register(
                RegistryType.PLATFORM_SERVICE,
                _req(name="Svc", dependencies=[DependencyRef(id="cap-ghost")]),
            )

    def test_consumers_are_derived_not_stored(self, service):
        capability = service.register(RegistryType.CAPABILITY, _req(name="Validation"))
        platform_service = service.register(
            RegistryType.PLATFORM_SERVICE,
            _req(name="Validation Service", dependencies=[DependencyRef(id=capability.id)]),
        )
        refreshed_capability = service.get(RegistryType.CAPABILITY, capability.id)
        assert refreshed_capability.consumers == [platform_service.id]

    def test_update_dependencies_recomputes_consumers(self, service):
        capability = service.register(RegistryType.CAPABILITY, _req(name="Scoring"))
        consumer = service.register(RegistryType.ENGINE, _req(name="Scoring Engine"))
        service.update(
            RegistryType.ENGINE, consumer.id,
            UpdateObjectRequest(dependencies=[DependencyRef(id=capability.id)]),
        )
        assert service.get(RegistryType.CAPABILITY, capability.id).consumers == [consumer.id]

    def test_transitive_dependencies_resolve_multiple_hops(self, service):
        a = service.register(RegistryType.DOMAIN, _req(name="A"))
        b = service.register(RegistryType.CAPABILITY, _req(name="B", dependencies=[DependencyRef(id=a.id)]))
        c = service.register(RegistryType.PRODUCT, _req(name="C", dependencies=[DependencyRef(id=b.id)]))
        result = service.transitive_dependencies(c.id)
        assert set(result["transitive_dependencies"]) == {a.id, b.id}
        assert result["cycles_detected"] == []

    def test_relationships_lists_direct_edges_only(self, service):
        a = service.register(RegistryType.DOMAIN, _req(name="A2"))
        b = service.register(RegistryType.CAPABILITY, _req(name="B2", dependencies=[DependencyRef(id=a.id)]))
        rel = service.relationships(b.id)
        assert rel["dependencies"] == [{"id": a.id, "required_version": None}]
        assert rel["consumers"] == []


class TestSearch:
    def test_search_by_query_matches_name_and_purpose(self, service):
        service.register(RegistryType.CAPABILITY, _req(name="Duplicate Detection", purpose="Finds duplicate capabilities."))
        service.register(RegistryType.CAPABILITY, _req(name="Version Negotiation"))
        results = service.search(query="duplicate")
        assert len(results) == 1
        assert results[0].name == "Duplicate Detection"

    def test_search_by_registry_type_and_owner(self, service):
        service.register(RegistryType.CAPABILITY, _req(name="X", owner="Nupur"))
        service.register(RegistryType.DOMAIN, _req(name="Y", owner="Nupur"))
        results = service.search(registry_type=RegistryType.CAPABILITY, owner="Nupur")
        assert len(results) == 1
        assert results[0].registry_type == RegistryType.CAPABILITY


class TestValidators:
    def test_classification_always_passes_by_construction(self, service):
        service.register(RegistryType.CAPABILITY, _req())
        report = service.validate_classification()
        assert report["passed"] is True

    def test_duplicate_name_within_same_registry_is_flagged(self, service):
        service.register(RegistryType.CAPABILITY, _req(name="Schema Validation"))
        service.register(RegistryType.CAPABILITY, _req(name="  schema validation  "))
        report = service.detect_duplicates()
        assert report["passed"] is False
        assert report["violations"][0]["type"] == "duplicate_name"

    def test_same_name_different_registries_is_not_a_duplicate(self, service):
        service.register(RegistryType.CAPABILITY, _req(name="Registry"))
        service.register(RegistryType.DOMAIN, _req(name="Registry"))
        report = service.detect_duplicates()
        assert report["passed"] is True

    def test_missing_authority_boundaries_flagged(self, service):
        service.register(RegistryType.CAPABILITY, _req(authority_boundaries=[]))
        report = service.validate_ownership()
        assert report["passed"] is False
        assert report["violations"][0]["reason"] == "missing_authority_boundaries"

    def test_undeclared_cross_owner_dependency_flagged(self, service):
        upstream = service.register(RegistryType.CAPABILITY, _req(name="Upstream", owner="Nupur"))
        service.register(
            RegistryType.PLATFORM_SERVICE,
            _req(name="Downstream", owner="Kavy", dependencies=[DependencyRef(id=upstream.id)]),
        )
        report = service.validate_authority_boundaries()
        assert report["passed"] is False
        assert report["violations"][0]["dependency_owner"] == "Nupur"

    def test_declared_cross_owner_dependency_passes(self, service):
        upstream = service.register(RegistryType.CAPABILITY, _req(name="Upstream2", owner="Nupur"))
        service.register(
            RegistryType.PLATFORM_SERVICE,
            _req(name="Downstream2", owner="Kavy", authority_boundaries=["Kavy", "Nupur"],
                 dependencies=[DependencyRef(id=upstream.id)]),
        )
        report = service.validate_authority_boundaries()
        assert report["passed"] is True

    def test_version_compatibility_flags_major_mismatch(self, service):
        upstream = service.register(RegistryType.CAPABILITY, _req(name="Upstream3", version="2.0"))
        service.register(
            RegistryType.PLATFORM_SERVICE,
            _req(name="Downstream3", dependencies=[DependencyRef(id=upstream.id, required_version="1.0")]),
        )
        report = service.validate_version_compatibility()
        assert report["passed"] is False
        assert report["violations"][0]["actual_version"] == "2.0"

    def test_version_compatibility_allows_minor_drift(self, service):
        upstream = service.register(RegistryType.CAPABILITY, _req(name="Upstream4", version="1.2"))
        service.register(
            RegistryType.PLATFORM_SERVICE,
            _req(name="Downstream4", dependencies=[DependencyRef(id=upstream.id, required_version="1.0")]),
        )
        report = service.validate_version_compatibility()
        assert report["passed"] is True

    def test_capability_reuse_check_finds_exact_and_similar(self, service):
        service.register(RegistryType.CAPABILITY, _req(name="Duplicate Detection"))
        result = service.capability_reuse_check("Duplicate Detection")
        assert result["reuse_recommended"] is True
        assert len(result["exact_matches"]) == 1

        similar = service.capability_reuse_check("Duplicate Detection Engine")
        assert similar["reuse_recommended"] is True
        assert len(similar["similar_matches"]) == 1

        none_found = service.capability_reuse_check("Completely Unrelated Thing")
        assert none_found["reuse_recommended"] is False

    def test_architecture_validation_is_replay_safe(self, service):
        service.register(RegistryType.CAPABILITY, _req())
        first = service.validate_architecture()
        second = service.validate_architecture()
        assert first["replay_hash"] == second["replay_hash"]
        assert first["passed"] is True

    def test_architecture_validation_hash_changes_when_state_changes(self, service):
        service.register(RegistryType.CAPABILITY, _req(name="First"))
        before = service.validate_architecture()
        service.register(RegistryType.CAPABILITY, _req(name="Second"))
        after = service.validate_architecture()
        assert before["replay_hash"] != after["replay_hash"]

    def test_dependency_integrity_flags_object_edited_to_point_nowhere(self, service):
        # Registration blocks dangling dependencies up front; this exercises
        # the re-verification path by mutating store state directly, the
        # scenario the check exists to catch (e.g. a hand-edited store).
        obj = service.register(RegistryType.CAPABILITY, _req())
        internal = service._store  # noqa: SLF001 - intentional white-box test
        data = internal.get(RegistryType.CAPABILITY, obj.id).model_dump()
        from bcaes_registry.models import DependencyRef, RegistryObject
        data["dependencies"] = [DependencyRef(id="cap-ghost")]
        internal._objects[RegistryType.CAPABILITY][obj.id] = RegistryObject(**data)
        report = service.validate_dependency_integrity()
        assert report["passed"] is False
        assert report["violations"][0]["missing_dependency"] == "cap-ghost"


class TestEdgeCasesAndErrors:
    def test_blank_name_rejected(self):
        with pytest.raises(Exception):
            RegisterObjectRequest(name="   ", purpose="p", owner="Kavy")

    def test_update_missing_object_raises(self, service):
        with pytest.raises(ObjectNotFoundError):
            service.update(RegistryType.CAPABILITY, "cap-ghost", UpdateObjectRequest(status=ObjectStatus.ACTIVE))

    def test_delete_missing_object_raises(self, service):
        with pytest.raises(ObjectNotFoundError):
            service.delete(RegistryType.CAPABILITY, "cap-ghost")

    def test_transitive_dependencies_detects_cycle(self, service):
        a = service.register(RegistryType.DOMAIN, _req(name="CycleA"))
        b = service.register(RegistryType.CAPABILITY, _req(name="CycleB", dependencies=[DependencyRef(id=a.id)]))
        # close the loop: A now also depends on B
        service.update(RegistryType.DOMAIN, a.id, UpdateObjectRequest(dependencies=[DependencyRef(id=b.id)]))
        result = service.transitive_dependencies(a.id)
        assert result["cycles_detected"], "expected the a->b->a loop to be reported"

    def test_duplicate_registered_id_is_flagged(self, service):
        obj = service.register(RegistryType.CAPABILITY, _req())
        # simulate a corrupted store where the same id appears under two
        # registries (should never happen via the public API)
        service._store._objects[RegistryType.DOMAIN][obj.id] = obj
        report = service.detect_duplicates()
        assert report["passed"] is False
        assert any(v["type"] == "duplicate_id" for v in report["violations"])
