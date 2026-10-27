#!/usr/bin/env python3
"""Validate consumer dataset contracts, shared schemas, and internal mappings."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACTS = ROOT / "datasets" / "dataset_contracts.json"
DEFAULT_SCHEMA = ROOT / "datasets" / "dataset_contract.schema.json"
DEFAULT_REGISTRY = ROOT / "datasets" / "internal_dataset_registry.json"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


def resolve_shared_schema(reference: str, shared_schemas: dict[str, Any]) -> tuple[str, Any] | None:
    prefix = "#/shared_schemas/"
    if not reference.startswith(prefix):
        return None
    schema_id = reference[len(prefix):]
    if not schema_id or "/" in schema_id or schema_id not in shared_schemas:
        return None
    return schema_id, shared_schemas[schema_id]


def validate_contracts(
    contracts_path: Path,
    schema_path: Path,
    registry_path: Path = DEFAULT_REGISTRY,
) -> list[str]:
    document = load_json(contracts_path)
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    if not isinstance(document, dict):
        return ["contracts document must be a JSON object"]

    schema_validator = Draft202012Validator(schema)
    errors = [
        f"document: {error.message}"
        for error in schema_validator.iter_errors(document)
    ]
    contracts = document.get("contracts")
    shared_schemas = document.get("shared_schemas")
    if not isinstance(contracts, list) or not isinstance(shared_schemas, dict):
        return errors

    capability_contracts: dict[str, str] = {}
    dataset_ids: dict[str, int] = {}
    for index, contract in enumerate(contracts):
        if not isinstance(contract, dict):
            continue
        dataset_id = contract.get("dataset_id", f"index {index}")
        capability_id = contract.get("capability_id")
        if isinstance(capability_id, str):
            if capability_id in capability_contracts:
                errors.append(
                    f"{dataset_id}: capability_id {capability_id!r} is already used by "
                    f"{capability_contracts[capability_id]!r}; capability IDs must be unique"
                )
            else:
                capability_contracts[capability_id] = dataset_id

        if isinstance(dataset_id, str):
            if dataset_id in dataset_ids:
                errors.append(f"{dataset_id}: dataset_id is duplicated")
            dataset_ids[dataset_id] = index

        if contains_key(contract, "source_file"):
            errors.append(f"{dataset_id}: consumer contract contains forbidden source_file")

        reference = contract.get("schema", {}).get("$ref") if isinstance(
            contract.get("schema"), dict
        ) else None
        if not isinstance(reference, str):
            continue
        resolved = resolve_shared_schema(reference, shared_schemas)
        if resolved is None:
            errors.append(f"{dataset_id}: schema reference {reference!r} does not resolve")

        allowed_domains = contract.get("allowed_domains")
        domain = contract.get("domain")
        if isinstance(allowed_domains, list) and domain not in allowed_domains:
            errors.append(f"{dataset_id}: domain must be included in allowed_domains")

        consumers = contract.get("allowed_consumers")
        if not isinstance(consumers, list):
            continue
        consumer_ids: set[str] = set()
        for consumer in consumers:
            if not isinstance(consumer, dict):
                continue
            consumer_id = consumer.get("consumer_id")
            if isinstance(consumer_id, str):
                if consumer_id in consumer_ids:
                    errors.append(f"{dataset_id}: consumer_id {consumer_id!r} is duplicated")
                consumer_ids.add(consumer_id)
            consumer_domain = consumer.get("domain")
            if isinstance(allowed_domains, list) and consumer_domain not in allowed_domains:
                errors.append(
                    f"{dataset_id}: consumer domain {consumer_domain!r} is not in allowed_domains"
                )

    for schema_id, shared_schema in shared_schemas.items():
        try:
            Draft202012Validator.check_schema(shared_schema)
        except SchemaError as error:
            errors.append(f"shared_schemas.{schema_id}: invalid JSON Schema: {error.message}")

    registry = load_json(registry_path)
    mappings = registry.get("capability_id_to_source_file") if isinstance(registry, dict) else None
    if not isinstance(mappings, dict):
        errors.append("internal registry must contain capability_id_to_source_file object")
    else:
        contract_capabilities = set(capability_contracts)
        registry_capabilities = set(mappings)
        for capability_id in sorted(contract_capabilities - registry_capabilities):
            errors.append(f"{capability_id}: missing source mapping in internal registry")
        for capability_id in sorted(registry_capabilities - contract_capabilities):
            errors.append(f"{capability_id}: internal registry has no consumer contract")
        for capability_id, source_file in mappings.items():
            if not isinstance(source_file, str) or not source_file.strip():
                errors.append(f"{capability_id}: internal source mapping must be a non-empty path")
            elif not (ROOT / source_file).is_file():
                errors.append(f"{capability_id}: internal source file does not exist: {source_file}")
        for contract in contracts:
            if not isinstance(contract, dict) or contract.get("contract_kind") != "synthetic_dataset":
                continue
            capability_id = contract.get("capability_id")
            source_file = mappings.get(capability_id)
            reference = contract.get("schema", {}).get("$ref")
            resolved = resolve_shared_schema(reference, shared_schemas) if isinstance(reference, str) else None
            if not isinstance(source_file, str) or resolved is None:
                continue
            try:
                dataset = load_json(ROOT / source_file)
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"{contract.get('dataset_id')}: cannot read synthetic dataset: {error}")
                continue
            data_validator = Draft202012Validator(
                resolved[1],
                format_checker=Draft202012Validator.FORMAT_CHECKER,
            )
            for error in data_validator.iter_errors(dataset):
                location = ".".join(str(part) for part in error.absolute_path)
                field = f" at {location}" if location else ""
                errors.append(
                    f"{contract.get('dataset_id')}{field}: synthetic data {error.message}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()

    try:
        errors = validate_contracts(args.contracts, args.schema, args.registry)
    except (OSError, json.JSONDecodeError, ValueError, SchemaError) as error:
        print(f"Unable to validate dataset contracts: {error}", file=sys.stderr)
        return 1

    if errors:
        print("Dataset contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    document = load_json(args.contracts)
    print(f"Validated {len(document['contracts'])} contracts and {len(document['shared_schemas'])} shared schemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
