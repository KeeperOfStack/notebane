# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install Python dependencies
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-alpine AS builder

WORKDIR /build

# Build deps for PyNaCl C extension
RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
# --pre allows yt-dlp nightly (needed for clearer "cookies invalid" error messages
# that the 2026.6.9 stable release buries under "Sign in to confirm your age")
RUN pip install --no-cache-dir --pre --prefix=/install -r requirements.txt

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — minimal Alpine + FFmpeg only
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-alpine

LABEL org.opencontainers.image.source="https://github.com/KeeperOfStack/notebane"
LABEL org.opencontainers.image.description="Lightweight Discord music bot powered by yt-dlp"
LABEL org.opencontainers.image.licenses="MIT"

# FFmpeg for audio pipeline (Opus passthrough); Deno provides the JS runtime
# yt-dlp uses to solve YouTube's signature/n-challenge (without it, age-gated
# and some normal videos return zero playable formats — only image storyboards).
# su-exec: lightweight privilege-drop (like gosu) for the entrypoint.
# shadow: provides usermod/groupmod so PUID/PGID remapping works at runtime.
RUN apk add --no-cache ffmpeg curl deno su-exec shadow

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source and entrypoint
COPY src/ /app/src/
COPY entrypoint.sh /entrypoint.sh

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    LOG_FORMAT=json \
    PUID=1000 \
    PGID=1000

# Create the notebane user/group that the entrypoint will remap to PUID/PGID
RUN addgroup -S notebane && adduser -S notebane -G notebane

# Pre-create volume mount points with correct ownership
RUN mkdir -p /cookies /data && chown notebane:notebane /cookies /data

# Health check: if METRICS_PORT is set, poll /health; otherwise skip (exit 0)
# The bot process itself keeps the container alive — if it crashes, Docker restarts it.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD sh -c '[ -z "${METRICS_PORT}" ] && exit 0; curl -fs http://127.0.0.1:${METRICS_PORT}/health > /dev/null 2>&1'

# Entrypoint runs as root, remaps uid/gid, fixes volume ownership, then drops privileges
ENTRYPOINT ["/entrypoint.sh"]
