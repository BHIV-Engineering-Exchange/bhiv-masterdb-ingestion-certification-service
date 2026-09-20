# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY main.py models.py ./
COPY auth auth/
COPY bcaes_registry bcaes_registry/
COPY canonical_repository canonical_repository/
COPY config config/
COPY database_targets database_targets/
COPY datasets datasets/
COPY engines engines/
COPY ingestion_jobs_store ingestion_jobs_store/
COPY knowledge_object_store knowledge_object_store/
COPY middleware middleware/
COPY operational_sync operational_sync/
COPY profiling profiling/
COPY registry_store registry_store/
COPY reports reports/
COPY retrieval_evidence_store retrieval_evidence_store/
COPY review_packets review_packets/
COPY scripts scripts/
COPY services services/
COPY shared_data shared_data/
COPY shared_store shared_store/
COPY tests tests/
COPY utils utils/
COPY validators validators/
COPY pytest.ini .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
