"""Shared across bcaes_registry and canonical_repository RBAC checks."""

# Holding this role bypasses per-object/per-document authority checks in
# both modules. There is exactly one of these, deliberately, rather than
# one admin role per module, so a real ops team has one thing to rotate
# access to instead of two.
ADMIN_ROLE = "bhiv-admin"
