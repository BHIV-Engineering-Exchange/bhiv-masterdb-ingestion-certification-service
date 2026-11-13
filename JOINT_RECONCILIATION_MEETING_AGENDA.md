# Joint MDU–MASTERDB Provenance & Lineage Reconciliation Meeting Agenda

**Meeting Purpose:** Align and finalize the MDU–MASTERDB joint data contracts, entity mapping, and live staging verification protocol under Raj's BIQOS P0 directive.  
**Participants:**
- Kavy Changela (MASTERDB Technical Owner)
- Nupur Gavane (MDU Semantic Authority)
- Raj (BIQOS Lead & Reviewer)
- Integration Engineering Team  

**Date / Time:** Scheduled upon delivery of reconciliation package  
**Handover Documents for Review:**
1. `MDU_HANDOVER_RESPONSE_NUPUR.md` (Verified MASTERDB Baseline)
2. `MASTERDB_PROVENANCE_LINEAGE_AUDIT.md` (Verified MASTERDB Technical Audit)
3. `MASTERDB_MDU_RECONCILIATION_DRAFT.md` (MASTERDB-Side Field Mapping & Blockers)

---

## Meeting Agenda

### 1. Opening & BIQOS P0 Scope Alignment (10 mins) — Lead: Raj
- Review of BIQOS P0 objectives: End-to-end trace continuity, deterministic lineage resolution, and immutable provenance audit trails across TANTRA, MASTERDB, and MDU.
- Establishment of evidential criteria for joint sign-off.

### 2. MDU Canonical Schema & OpenAPI v1 Walkthrough (15 mins) — Lead: Nupur
- MDU core entities: `DatasetResponse`, `ProvenanceResponse`, `RelationshipResponse`.
- Clarification of canonical dataset identifier (`canonical_id`) vs internal UUID (`id`).
- OpenAPI v1 endpoint constraints and authorization roles (`ApiKeyRole.CONTRIBUTOR` vs `REGISTRY_ADMIN`).

### 3. MASTERDB Implementation & Expected Schema Walkthrough (15 mins) — Lead: Kavy
- Walkthrough of MASTERDB intake: `UploadJob` -> `IngestJob` -> `KnowledgePackage` -> `KnowledgeObject`.
- Demonstration of `MDUContractAdapter` and `MDUClient` architecture.
- Review of 21 passing automated tests in `tests/test_mdu_provenance_integration.py` and `tests/test_mdu_contract_adapter.py`.

### 4. Field-by-Field Mapping & Semantic Reconciliation (25 mins) — Joint: Kavy & Nupur
- Review of the 14 core mapping rows in `MASTERDB_MDU_RECONCILIATION_DRAFT.md`:
  - **Entity Identity:** Formalizing `knowledge_object_id` as internal to MASTERDB and linking to MDU via `canonical_id` and `lineage_reference`.
  - **Source Reference:** Confirming 1:1 pass-through of `source_reference` into MDU event logs.
  - **Lineage Representation:** Mapping MASTERDB parent packages to MDU dataset relationship edges (`parent_dataset_id`, `relationship_type="DERIVED_FROM"`).
  - **Derivation Path:** Confirming serialization of `derivation_path` into `transformation_reference` / `transformation_notes`.
  - **Lifecycle States:** Harmonizing package transitions with MDU dataset trust levels (`PROVISIONAL`, `TRUSTED`, `VERIFIED`).

### 5. Lineage Validation & Certification Protocol (15 mins) — Joint
- Defining what constitutes sufficient evidence for lineage validation before TANTRA retrieval.
- Review of MDU `/api/v1/discovery/provenance/validate/{id}` probe requirements (`tantra_ready: true`).
- Boundary definition: Certification report generation in MASTERDB vs Trust level update in MDU.

### 6. Outstanding Blockers & Technical Questions (15 mins) — Joint
- **Parakosha API Key Provisioning:** Resolving HTTP 401 on `https://parakosha.blackholeinfiverse.com`.
- **Sandbox Dataset Assignment:** Designating `BHIV-DS-TEST-INGEST-001` for safe remote live-write testing.
- **Render Production Environment Update:** Coordinating zero-downtime redeployment of MASTERDB once Parakosha credentials are active.

### 7. Action Items & Final Approval Roadmap (10 mins) — Lead: Raj
- Finalization of joint contract `MDU_PROVENANCE_LINEAGE_CONTRACT.md`.
- Assignment of implementation deadlines for outstanding items.
- Scheduling of staging live-write execution test.

