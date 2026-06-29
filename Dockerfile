# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install Python dependencies
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-alpine AS builder

WORKDIR /build

# Install build deps (needed by PyNaCl's C extension)
RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — minimal Alpine + FFmpeg only
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-alpine

# FFmpeg for audio pipeline (Opus passthrough)
RUN apk add --no-cache ffmpeg

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ /app/src/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Run as non-root
RUN addgroup -S notebane && adduser -S notebane -G notebane
USER notebane

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import discord; print('ok')" || exit 1

ENTRYPOINT ["python", "-m", "notebane"]
