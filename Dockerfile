# syntax=docker/dockerfile:1
# ==============================================================================
# Darkstar Energy Manager - Production Dockerfile
# Single-stage build using Debian (python:3.12-slim)
# Supports amd64 (servers) and arm64 (Raspberry Pi)
# ==============================================================================

FROM python:3.12-slim

LABEL maintainer="Darkstar Energy Manager"
LABEL description="AI-powered home battery optimization"

WORKDIR /app

# Install system dependencies
# - nodejs, npm: Frontend build
# - libgomp1: Required for LightGBM
# - curl: Health checks
# - gcc, g++, make: Build dependencies for packages that need compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    libgomp1 \
    curl \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install pnpm globally. Pinned to v9 to match CI (pnpm/action-setup version: 9)
# and frontend/pnpm-lock.yaml. pnpm 10 requires Node 22's `node:sqlite` builtin,
# which the Debian Node in this image does not provide.
RUN npm install -g pnpm@9

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy frontend package files first for layer caching
COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN cd frontend && pnpm install --frozen-lockfile

# Copy application code
COPY backend/ ./backend/
COPY planner/ ./planner/
COPY executor/ ./executor/
COPY profiles/ ./profiles/
COPY bin/ ./bin/
COPY ml/*.py ./ml/
RUN mkdir -p ml/models
COPY ml/models/defaults/ ./ml/models/defaults/
COPY utils/ ./utils/
COPY scripts/ ./scripts/
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Alembic migrations
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Copy default configuration (users mount their own config.yaml)
COPY VERSION ./VERSION
COPY config.default.yaml ./config.default.yaml
COPY secrets.example.yaml ./secrets.example.yaml
COPY ml/regions.json ./ml/regions.json

# Build frontend (Vite outputs to backend/static, FastAPI serves from there)
COPY frontend/ ./frontend/
RUN cd frontend && pnpm build

# Copy Vite's index.html to templates folder (it has the correct asset hashes)
RUN mkdir -p ./backend/templates && \
    cp ./backend/static/index.html ./backend/templates/index.html

# Create directories for runtime data
RUN mkdir -p /data

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV APP_MODULE=backend.main:app

# Health check
HEALTHCHECK --interval=30s --timeout=20s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Expose port
EXPOSE 5000

# Start all services (scheduler, recorder, FastAPI)
CMD ["/entrypoint.sh"]
