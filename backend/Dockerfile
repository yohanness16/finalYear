# ──────────────────────────────────────────────────────────────────────────────
# BusTrack — Production Dockerfile (Multi-stage)
# ──────────────────────────────────────────────────────────────────────────────
# Build:
#   docker build -t bustrack-api .
#
# Run:
#   docker run -p 8000:8000 --env-file .env bustrack-api
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /build

# Install build dependencies
RUN apt-get update --fix-missing && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv

# Activate venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy requirements first (better Docker caching)
COPY requirements.txt .
COPY requirements-ml.txt .

# Install Python dependencies (base always, ML extras for production YOLO)
ARG INSTALL_ML=false
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$INSTALL_ML" = "true" ]; then \
        pip install --no-cache-dir -r requirements-ml.txt; \
    fi

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Python optimizations
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /usr/sbin/nologin appuser

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update --fix-missing && apt-get install -y --no-install-recommends \
    libpq5 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Activate virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Copy application files
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Create storage directories
RUN mkdir -p /app/storage/esp32_images && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose FastAPI port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start application with Gunicorn + Uvicorn workers
CMD ["gunicorn", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "2", \
     "-b", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "app.main:app"]