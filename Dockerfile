# =====================================================================
# Media Sorter - Production Multi-Stage Dockerfile
# =====================================================================

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir build && \
    python -m build --wheel

# ---------------------------------------------------------------------
# Final Production Runtime Image
# ---------------------------------------------------------------------
FROM python:3.12-slim AS runner

LABEL org.opencontainers.image.title="Media Sorter" \
      org.opencontainers.image.description="Reliable, high-performance media classification and organization system" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    mediainfo \
    ffmpeg \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-privileged user and group
RUN groupadd -g 1000 mediasorter && \
    useradd -u 1000 -g mediasorter -m -s /bin/bash mediasorter && \
    mkdir -p /media/incoming /media/organized /config /data && \
    chown -R mediasorter:mediasorter /media /config /data /app

# Copy wheel from builder and install
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Default environment variables
ENV PYTHONUNBUFFERED=1 \
    MEDIA_SORTER_DATABASE__PATH=/data/media_sorter.db \
    MEDIA_SORTER_STORAGE__SOURCE_DIRS='["/media/incoming"]' \
    MEDIA_SORTER_STORAGE__DESTINATION_BASE=/media/organized \
    MEDIA_SORTER_SERVER__HOST=0.0.0.0 \
    MEDIA_SORTER_SERVER__PORT=8080

EXPOSE 8080

# Healthcheck testing the REST status endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/status || exit 1

# Run as non-root user
USER mediasorter

ENTRYPOINT ["media-sorter"]
CMD ["server", "--host", "0.0.0.0", "--port", "8080", "--config", "/config/config.yaml"]
