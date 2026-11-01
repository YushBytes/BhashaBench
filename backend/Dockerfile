# syntax=docker/dockerfile:1

# =============================================================================
# BhashaBench backend image
# =============================================================================
# Python 3.12 is pinned explicitly: it is the version the project targets
# (see `requires-python` and Ruff's `target-version`), so the container matches
# CI regardless of what the developer has installed locally.
FROM python:3.12-slim AS base

# PYTHONDONTWRITEBYTECODE: no .pyc clutter in the image layer.
# PYTHONUNBUFFERED:        logs reach `docker logs` immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# curl is needed by the Compose health check below.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies are copied and installed before application code so that the
# (slow) install layer is cached across code-only changes.
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install -r requirements.txt

# -----------------------------------------------------------------------------
# Development target: dev dependencies plus hot reload.
# -----------------------------------------------------------------------------
FROM base AS development

RUN pip install -r requirements-dev.txt

COPY backend/ /app/

# Run as a non-root user even in development.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# -----------------------------------------------------------------------------
# Production target: no dev dependencies, no reload.
# -----------------------------------------------------------------------------
FROM base AS production

COPY backend/ /app/

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
