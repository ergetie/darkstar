# Darkstar Energy Manager - Home Assistant Add-on Dockerfile
# Built for multi-arch (amd64, arm64)
# Build context is repo root

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Node.js and npm for frontend build
    nodejs \
    npm \
    # Utilities
    curl \
    jq \
    bash \
    # GLPK solver for PuLP (Kepler optimizer)
    glpk-utils \
    libglpk-dev \
    # Build dependencies for any packages that need compilation
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pnpm and build frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN npm install -g pnpm && cd frontend && pnpm install --frozen-lockfile

# Install Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code (except frontend)
COPY backend/ ./backend/
COPY planner/ ./planner/
COPY executor/ ./executor/
COPY bin/ ./bin/
COPY ml/*.py ./ml/
COPY ml/models/*.lgb ./ml/models/
COPY inputs.py ./

# Copy frontend source and build (AFTER copying backend to avoid overwriting static assets)
COPY frontend/ ./frontend/
RUN cd frontend && pnpm build

# Copy configuration templates
COPY config.default.yaml ./
COPY secrets.example.yaml ./
COPY VERSION ./

# Copy HA Add-on entrypoint (note: path from repo root context)
COPY darkstar-dev/run.sh /run.sh
RUN chmod +x /run.sh

# Environment

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["/run.sh"]

