# MASTERDB INGESTION & UPLOAD SERVICE — API CONTRACT DOCUMENTATION

## 1. POST /auth/token

* **METHOD:** `POST`
* **PATH:** `/auth/token`
* **AUTHENTICATION:** None (Public Endpoint)
* **ROLES:** N/A
* **REQUEST HEADERS:** `Content-Type: application/json`
* **REQUEST BODY:**
  ```json
  {
    "actor": "string",
    "password": "string (optional)",
    "roles": ["string (optional)"]
  }
  ```
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1Ni...",
    "token_type": "bearer",
    "actor": "kavy",
    "roles": ["bhiv-admin", "operator", "admin"],
    "expires_at": "2026-09-30T17:30:00+00:00"
  }
  ```
* **ERROR STATUS:** `401 Unauthorized`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Invalid credentials.",
      "path": "/auth/token"
    }
  }
  ```

---

## 2. GET /databases

* **METHOD:** `GET`
* **PATH:** `/databases`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Any valid authenticated identity
* **REQUEST HEADERS:** `Authorization: Bearer <token>`
* **REQUEST BODY:** None
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  [
    {
      "key": "RelationalDB",
      "display_name": "MASTERDB Relational Store",
      "description": "SQL relational target store",
      "accepted_formats": ["csv", "json"],
      "required_role": "ingest:relationaldb"
    }
  ]
  ```
* **ERROR STATUS:** `401 Unauthorized`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Missing bearer token. Obtain one from POST /auth/token.",
      "path": "/databases"
    }
  }
  ```

---

## 3. GET /databases/{database_key}

* **METHOD:** `GET`
* **PATH:** `/databases/{database_key}`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Any valid authenticated identity
* **REQUEST HEADERS:** `Authorization: Bearer <token>`
* **REQUEST BODY:** None
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  {
    "key": "RelationalDB",
    "display_name": "MASTERDB Relational Store",
    "description": "SQL relational target store",
    "accepted_formats": ["csv", "json"],
    "required_role": "ingest:relationaldb"
  }
  ```
* **ERROR STATUS:** `404 Not Found`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Unknown target database 'InvalidDB'.",
      "path": "/databases/InvalidDB"
    }
  }
  ```

---

## 4. POST /upload

* **METHOD:** `POST`
* **PATH:** `/upload`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Any valid authenticated identity
* **REQUEST HEADERS:** `Authorization: Bearer <token>`, `Content-Type: application/json`
* **REQUEST BODY:**
  ```json
  {
    "filename": "dataset.csv",
    "content_type": "text/csv",
    "file_size": 1024,
    "checksum_sha256": "string (optional)",
    "intended_use": "Analytics"
  }
  ```
* **SUCCESS STATUS:** `201 Created`
* **SUCCESS RESPONSE:**
  ```json
  {
    "upload_id": "upload-a1b2c3d4e5f6",
    "trace_id": "trace-9876543210fe",
    "status": "UPLOADED",
    "storage_path": "upload_staging/upload-a1b2c3d4e5f6/dataset.csv",
    "max_size_bytes": 524288000,
    "allowed_content_types": ["text/csv", "application/json"],
    "checksum_algorithm": "sha256"
  }
  ```
* **ERROR STATUS:** `400 Bad Request`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Content type 'invalid/type' not allowed.",
      "path": "/upload"
    }
  }
  ```

---

## 5. POST /upload/{upload_id}/content

* **METHOD:** `POST`
* **PATH:** `/upload/{upload_id}/content`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Upload Owner, `bhiv-admin`, or `operator`
* **REQUEST HEADERS:** `Authorization: Bearer <token>`, `Content-Type: application/octet-stream`
* **REQUEST BODY:** Raw binary bytes of file content
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  {
    "upload_id": "upload-a1b2c3d4e5f6",
    "status": "RECEIVED",
    "file_size_bytes": 1024
  }
  ```
* **ERROR STATUS:** `403 Forbidden` / `404 Not Found`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Not authorized to modify upload 'upload-a1b2c3d4e5f6' owned by 'other_user'.",
      "path": "/upload/upload-a1b2c3d4e5f6/content"
    }
  }
  ```

---

## 6. POST /upload/{upload_id}/validate

* **METHOD:** `POST`
* **PATH:** `/upload/{upload_id}/validate`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Upload Owner, `bhiv-admin`, or `operator`
* **REQUEST HEADERS:** `Authorization: Bearer <token>`
* **REQUEST BODY:** None
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  {
    "upload_id": "upload-a1b2c3d4e5f6",
    "status": "VALIDATED",
    "validation_passed": true,
    "rejection_reason": null,
    "steps": [
      {
        "step": "CHECKSUM_VERIFICATION",
        "passed": true,
        "detail": "Checksum verified."
      }
    ]
  }
  ```
* **ERROR STATUS:** `409 Conflict`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Upload state must be RECEIVED to validate.",
      "path": "/upload/upload-a1b2c3d4e5f6/validate"
    }
  }
  ```

---

## 7. GET /upload/jobs/{upload_id}

* **METHOD:** `GET`
* **PATH:** `/upload/jobs/{upload_id}`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Upload Owner, `bhiv-admin`, or `operator`
* **REQUEST HEADERS:** `Authorization: Bearer <token>`
* **REQUEST BODY:** None
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  {
    "upload_id": "upload-a1b2c3d4e5f6",
    "status": "VALIDATED",
    "filename": "dataset.csv",
    "content_type": "text/csv",
    "file_size_bytes": 1024,
    "actor": "kavy",
    "steps": [],
    "rejection_reason": null,
    "dataset_id": "certifiable",
    "package_id": null,
    "ingestion_job_id": null,
    "timestamps": {
      "uploaded_at": "2026-09-30T16:00:00+00:00",
      "received_at": "2026-09-30T16:01:00+00:00",
      "validated_at": "2026-09-30T16:02:00+00:00",
      "registered_at": null
    }
  }
  ```
* **ERROR STATUS:** `403 Forbidden`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Not authorized to view upload 'upload-a1b2c3d4e5f6' owned by 'other_user'.",
      "path": "/upload/jobs/upload-a1b2c3d4e5f6"
    }
  }
  ```

---

## 8. GET /upload/jobs

* **METHOD:** `GET`
* **PATH:** `/upload/jobs`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Any authenticated user (non-admin filtered strictly to self uploads)
* **REQUEST HEADERS:** `Authorization: Bearer <token>`
* **QUERY PARAMS:** `status`, `actor`, `product_source`
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  {
    "count": 1,
    "uploads": [
      {
        "upload_id": "upload-a1b2c3d4e5f6",
        "status": "VALIDATED",
        "filename": "dataset.csv",
        "file_size_bytes": 1024,
        "actor": "kavy",
        "product_source": null,
        "uploaded_at": "2026-09-30T16:00:00+00:00"
      }
    ]
  }
  ```

---

## 9. DELETE /upload/jobs/{upload_id}

* **METHOD:** `DELETE`
* **PATH:** `/upload/jobs/{upload_id}`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Upload Owner, `bhiv-admin`, or `operator`
* **REQUEST HEADERS:** `Authorization: Bearer <token>`, `Content-Type: application/json`
* **REQUEST BODY:**
  ```json
  {
    "reason": "Duplicate upload attempt"
  }
  ```
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:**
  ```json
  {
    "upload_id": "upload-a1b2c3d4e5f6",
    "status": "CANCELLED",
    "rejection_reason": "Duplicate upload attempt"
  }
  ```

---

## 10. POST /ingest

* **METHOD:** `POST`
* **PATH:** `/ingest`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Target database specific role (e.g. `ingest:relationaldb`), `bhiv-admin`, or `operator`
* **REQUEST HEADERS:** `Authorization: Bearer <token>`, `Content-Type: application/json`
* **REQUEST BODY:**
  ```json
  {
    "dataset_id": "certifiable",
    "target_database": "RelationalDB",
    "source_format": "csv",
    "upload_id": "upload-a1b2c3d4e5f6 (optional)",
    "package_id": "string (optional)",
    "metadata": {}
  }
  ```
* **SUCCESS STATUS:** `201 Created`
* **SUCCESS RESPONSE:**
  ```json
  {
    "job_id": "job-1234567890ab",
    "dataset_id": "certifiable",
    "target_database": "RelationalDB",
    "source_format": "csv",
    "package_id": null,
    "actor": "kavy",
    "roles": ["ingest:relationaldb"],
    "status": "PERSISTED",
    "certification_state": "CERTIFIED",
    "integrity_score": 95.0,
    "steps": [
      {
        "step": "RBAC_CHECK",
        "passed": true,
        "detail": "actor holds required role 'ingest:relationaldb'"
      },
      {
        "step": "FORMAT_CHECK",
        "passed": true,
        "detail": "'csv' accepted by RelationalDB"
      },
      {
        "step": "CERTIFICATION_GATE",
        "passed": true,
        "detail": "dataset is CERTIFIED and eligible_for_masterdb=True"
      },
      {
        "step": "PERSISTENCE",
        "passed": true,
        "detail": "Persisted 5 records to RelationalDB (RelationalDB/certifiable)."
      },
      {
        "step": "ROUTED",
        "passed": true,
        "detail": "Routed to RelationalDB."
      }
    ],
    "rejection_reason": null,
    "metadata": {
      "target_reference": "RelationalDB/certifiable",
      "records_persisted": 5
    },
    "submitted_at": "2026-09-30T16:05:00+00:00",
    "completed_at": "2026-09-30T16:05:01+00:00"
  }
  ```
* **ERROR STATUS:** `403 Forbidden` / `422 Unprocessable Entity`
* **ERROR RESPONSE:**
  ```json
  {
    "error": {
      "type": "http_error",
      "message": "Dataset 'certifiable' is not CERTIFIED for MASTERDB ingestion. (job_id=job-1234567890ab)",
      "path": "/ingest"
    }
  }
  ```

---

## 11. GET /ingest/jobs/{job_id}

* **METHOD:** `GET`
* **PATH:** `/ingest/jobs/{job_id}`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Any authenticated identity
* **REQUEST HEADERS:** `Authorization: Bearer <token>`
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:** Same schema as IngestJob response above.

---

## 12. GET /ingest/jobs

* **METHOD:** `GET`
* **PATH:** `/ingest/jobs`
* **AUTHENTICATION:** Required (`Bearer <JWT>`)
* **ROLES:** Any authenticated identity
* **QUERY PARAMS:** `dataset_id`, `target_database`, `status`
* **SUCCESS STATUS:** `200 OK`
* **SUCCESS RESPONSE:** List of IngestJob JSON objects.

---

## CONTRACT CHANGE CONTROL CLASSIFICATION

No frontend-facing API contract changes. All modified endpoints adhere strictly to existing Pydantic request and response models.
