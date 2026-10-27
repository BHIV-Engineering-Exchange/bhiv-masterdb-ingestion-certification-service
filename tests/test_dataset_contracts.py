import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts import validate_dataset_contracts as contract_validator
from scripts.validate_dataset_contracts import (
    DEFAULT_CONTRACTS,
    DEFAULT_REGISTRY,
    DEFAULT_SCHEMA,
    validate_contracts,
)


def test_all_consumer_dataset_contracts_match_schema():
    assert validate_contracts(DEFAULT_CONTRACTS, DEFAULT_SCHEMA) == []


def test_contract_schema_rejects_source_file_at_any_depth():
    schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    contract = json.loads(DEFAULT_CONTRACTS.read_text(encoding="utf-8"))["contracts"][0]

    contract["provenance"]["lineage"] = {"source_file": "private/path.csv"}
    assert list(validator.iter_errors(contract))


def test_registry_is_separate_from_consumer_contracts():
    contracts = json.loads(DEFAULT_CONTRACTS.read_text(encoding="utf-8"))["contracts"]
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))

    for contract in contracts:
        assert not contains_source_file_key(contract)
        assert contract["capability_id"] in registry["capability_id_to_source_file"]


def test_capability_ids_must_be_unique(tmp_path, monkeypatch):
    contracts_document = json.loads(DEFAULT_CONTRACTS.read_text(encoding="utf-8"))
    contracts_document["contracts"][1]["capability_id"] = contracts_document["contracts"][0][
        "capability_id"
    ]
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps(contracts_document), encoding="utf-8")
    monkeypatch.setattr(contract_validator, "ROOT", Path(__file__).resolve().parents[1])

    errors = validate_contracts(contracts_path, DEFAULT_SCHEMA, DEFAULT_REGISTRY)

    assert any("capability IDs must be unique" in error for error in errors)


def test_failure_fixtures_are_internal_and_consumers_are_machine_checkable():
    contracts_document = json.loads(DEFAULT_CONTRACTS.read_text(encoding="utf-8"))
    for contract in contracts_document["contracts"]:
        assert all(
            set(consumer) == {"consumer_id", "name", "domain"}
            for consumer in contract["allowed_consumers"]
        )
        if contract.get("contract_kind") == "failure_fixture":
            assert contract["status"] == "internal"
            assert contract["visibility"] == "internal"


def test_three_synthetic_domain_contracts_are_present():
    contracts = json.loads(DEFAULT_CONTRACTS.read_text(encoding="utf-8"))["contracts"]
    synthetic_ids = {
        contract["dataset_id"]
        for contract in contracts
        if contract.get("contract_kind") == "synthetic_dataset"
    }

    assert {"ds-mangrove-001", "ds-maritime-001", "ds-fin-001"} <= synthetic_ids


def contains_source_file_key(value):
    if isinstance(value, dict):
        return "source_file" in value or any(
            contains_source_file_key(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(contains_source_file_key(child) for child in value)
    return False
