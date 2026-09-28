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
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code (tests and pytest.ini excluded via .dockerignore)
COPY main.py models.py ./
COPY api api/
COPY auth auth/
COPY bcaes_registry bcaes_registry/
COPY canonical_repository canonical_repository/
COPY config config/
COPY database_targets database_targets/
COPY datasets datasets/
COPY engines engines/
COPY evaluation_engine evaluation_engine/
COPY ingestion_jobs_store ingestion_jobs_store/
COPY integrations integrations/
COPY knowledge_object_store knowledge_object_store/
COPY middleware middleware/
COPY operational_sync operational_sync/
COPY profiling profiling/
COPY registry_store registry_store/
COPY reports reports/
COPY retrieval_evidence_store retrieval_evidence_store/
COPY review_packets review_packets/
COPY scripts scripts/
COPY security security/
COPY services services/
COPY shared_data shared_data/
COPY shared_store shared_store/
COPY task_selector task_selector/
COPY upload upload/
COPY utils utils/
COPY validators validators/

# Create required runtime directories with correct permissions
RUN mkdir -p /app/reports /app/registry_store /app/knowledge_object_store \
    /app/retrieval_evidence_store /app/shared_store \
    /app/ingestion_jobs_store /app/review_packets && \
    chmod 755 /app/reports /app/registry_store /app/knowledge_object_store \
    /app/retrieval_evidence_store /app/shared_store \
    /app/ingestion_jobs_store /app/review_packets

# Create non-root user with home directory
RUN useradd -m -u 1000 -s /sbin/nologin appuser

# Set ownership of app directory to appuser
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check using Python (more reliable than curl)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()" || exit 1
# Run application with explicit worker settings for stability
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
