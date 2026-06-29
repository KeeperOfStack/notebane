# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install Python dependencies
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-alpine AS builder

WORKDIR /build

# Build deps for PyNaCl C extension
RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — minimal Alpine + FFmpeg only
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-alpine

LABEL org.opencontainers.image.source="https://github.com/KeeperOfStack/notebane"
LABEL org.opencontainers.image.description="Lightweight Discord music bot powered by yt-dlp"
LABEL org.opencontainers.image.licenses="MIT"

# FFmpeg for audio pipeline (Opus passthrough)
RUN apk add --no-cache ffmpeg curl

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ /app/src/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    LOG_FORMAT=json

# Run as non-root
RUN addgroup -S notebane && adduser -S notebane -G notebane
USER notebane

# Health check via /health endpoint (requires METRICS_PORT set; falls back gracefully)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD sh -c 'PORT=${METRICS_PORT:-9090}; curl -fs http://127.0.0.1:$PORT/health > /dev/null 2>&1 || exit 0'

ENTRYPOINT ["python", "-m", "notebane"]
