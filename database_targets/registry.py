"""
Static capability contract for the 8 MASTERDB target databases.

Discoverable via `GET /databases` so the Dashboard & Control Center
(Rahil's surface) never hardcodes target names, accepted formats, or the
role required to ingest into a given database — it reads this contract,
per the task's "Supported targets must be discoverable through a stable
contract" requirement. Extending to a 9th database is additive: add one
entry here, nothing else changes.

`required_role` follows a per-database naming convention
(`ingest:<database-key>`) so read/write/ingest/modify/export/admin
authority stay separable per the task's security requirements — holding
`ingest:vectordb` grants nothing on GraphDB, and vice versa. `ADMIN_ROLE`
(see `auth/constants.py`) bypasses all of them, matching the one-role
ops-bypass pattern already used by bcaes_registry/canonical_repository.
"""
from database_targets.models import DatabaseCapability, IngestionFormat, TargetDatabase

_ALL_FORMATS = list(IngestionFormat)

DATABASE_REGISTRY: dict = {
    TargetDatabase.VECTOR_DB: DatabaseCapability(
        key=TargetDatabase.VECTOR_DB,
        display_name="VectorDB",
        description="Embeddings, semantic search.",
        accepted_formats=[IngestionFormat.JSON, IngestionFormat.CSV],
        required_role="ingest:vectordb",
    ),
    TargetDatabase.GRAPH_DB: DatabaseCapability(
        key=TargetDatabase.GRAPH_DB,
        display_name="GraphDB",
        description="Knowledge graph, relationships.",
        accepted_formats=[IngestionFormat.JSON, IngestionFormat.CSV],
        required_role="ingest:graphdb",
    ),
    TargetDatabase.METADATA_DB: DatabaseCapability(
        key=TargetDatabase.METADATA_DB,
        display_name="MetadataDB",
        description="Dataset registry, metadata.",
        accepted_formats=_ALL_FORMATS,
        required_role="ingest:metadatadb",
    ),
    TargetDatabase.DOCUMENT_DB: DatabaseCapability(
        key=TargetDatabase.DOCUMENT_DB,
        display_name="DocumentDB",
        description="Documents, unstructured data.",
        accepted_formats=[
            IngestionFormat.PDF,
            IngestionFormat.TXT,
            IngestionFormat.IMAGE,
            IngestionFormat.JSON,
        ],
        required_role="ingest:documentdb",
    ),
    TargetDatabase.TIME_SERIES_DB: DatabaseCapability(
        key=TargetDatabase.TIME_SERIES_DB,
        display_name="TimeSeriesDB",
        description="Sensor, telemetry, time-series data.",
        accepted_formats=[IngestionFormat.CSV, IngestionFormat.JSON],
        required_role="ingest:timeseriesdb",
    ),
    TargetDatabase.RELATIONAL_DB: DatabaseCapability(
        key=TargetDatabase.RELATIONAL_DB,
        display_name="RelationalDB",
        description="Structured, tabular data.",
        accepted_formats=[IngestionFormat.CSV, IngestionFormat.XLSX, IngestionFormat.JSON],
        required_role="ingest:relationaldb",
    ),
    TargetDatabase.ARCHIVE_DB: DatabaseCapability(
        key=TargetDatabase.ARCHIVE_DB,
        display_name="ArchiveDB",
        description="Long-term storage, cold data.",
        accepted_formats=_ALL_FORMATS,
        required_role="ingest:archivedb",
    ),
    TargetDatabase.ANALYTICS_DB: DatabaseCapability(
        key=TargetDatabase.ANALYTICS_DB,
        display_name="AnalyticsDB",
        description="Aggregated, analytical datasets.",
        accepted_formats=[IngestionFormat.CSV, IngestionFormat.JSON, IngestionFormat.XLSX],
        required_role="ingest:analyticsdb",
    ),
}
