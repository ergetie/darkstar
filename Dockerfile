# syntax=docker/dockerfile:1
# ==============================================================================
# Darkstar Energy Manager - Production Dockerfile
# Multi-stage build for small image size (~300MB)
# Supports amd64 (servers) and arm64 (Raspberry Pi)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Frontend
# ------------------------------------------------------------------------------
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install pnpm
RUN npm install -g pnpm

# Copy package files first for layer caching
COPY frontend/package.json frontend/pnpm-lock.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source and build
COPY frontend/ ./
RUN pnpm build

# ------------------------------------------------------------------------------
# Stage 2: Python Runtime
# ------------------------------------------------------------------------------
FROM python:3.12-slim

LABEL maintainer="Darkstar Energy Manager"
LABEL description="AI-powered home battery optimization"

WORKDIR /app

# Install system dependencies
# - libgomp1: Required for LightGBM
# - curl: Health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY planner/ ./planner/
COPY executor/ ./executor/
COPY ml/*.py ./ml/
COPY ml/models/*.lgb ./ml/models/
COPY inputs.py db_writer.py ./
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy default configuration (users mount their own config.yaml)
COPY config.default.yaml ./config.default.yaml
COPY secrets.example.yaml ./secrets.example.yaml

# Copy built frontend from stage 1 (Vite outputs to backend/static, Flask serves from there)
COPY --from=frontend-builder /app/backend/static ./backend/static

# Copy Vite's index.html to templates folder (it has the correct asset hashes)
RUN mkdir -p ./backend/templates && \
    cp ./backend/static/index.html ./backend/templates/index.html

# Create directories for runtime data
RUN mkdir -p /data

# Environment variables
ENV FLASK_APP=backend.webapp
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/status || exit 1

# Expose port
EXPOSE 5000

# Start all services (scheduler, recorder, Flask)
CMD ["/entrypoint.sh"]
