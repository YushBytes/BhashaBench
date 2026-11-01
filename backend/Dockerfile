# syntax=docker/dockerfile:1

# =============================================================================
# BhashaBench backend image
# =============================================================================
# Python 3.12 is pinned explicitly: it is the version the project targets
# (see `requires-python` and Ruff's `target-version`), so the container matches
# CI regardless of what the developer has installed locally.
FROM python:3.12-slim AS base

# PIP_DEFAULT_TIMEOUT / PIP_RETRIES: pip's 15s default read timeout is too
# short on connections with unreliable sustained throughput. Observed here:
# pip established the HTTPS connection to files.pythonhosted.org but the
# read stalled, failing with "TimeoutError: The read operation timed out"
# and the misleading "No matching distribution found". With these values the
# same install completes in ~220s. They only raise patience, never relax
# version resolution, so the pinned requirements still bind exactly.
# PYTHONDONTWRITEBYTECODE: no .pyc clutter in the image layer.
# PYTHONUNBUFFERED:        logs reach `docker logs` immediately.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# curl is needed by the Compose health check below.
#
# Acquire::ForceIPv4 is deliberate. deb.debian.org publishes both A and AAAA
# records, and apt tries the AAAA address first. On a host whose Docker build
# network has no working IPv6 egress the connection is blackholed rather than
# refused, so apt retries with long timeouts and the build hangs indefinitely
# (observed here: >25 minutes with no output, versus ~30 seconds with this
# flag). Forcing IPv4 makes the build deterministic on such networks, and is
# a no-op where IPv6 works.
RUN apt-get -o Acquire::ForceIPv4=true update \
    && apt-get -o Acquire::ForceIPv4=true install --no-install-recommends -y curl \
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
