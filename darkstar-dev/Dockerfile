# Darkstar Energy Manager - Home Assistant Add-on Dockerfile
# Built for multi-arch (amd64, arm64)
# Build context is repo root

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Utilities
    curl \
    ca-certificates \
    gnupg \
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

# Install Node 22 from NodeSource (Debian's apt `nodejs` is too old for pnpm 10's
# `node:sqlite` requirement).
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pnpm and build frontend. pnpm pinned to v10 to match CI and the lockfile.
COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN npm install -g pnpm@10 && cd frontend && pnpm install --frozen-lockfile

# Install Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code (except frontend)
COPY backend/ ./backend/
COPY planner/ ./planner/
COPY executor/ ./executor/
COPY bin/ ./bin/
COPY profiles/ ./profiles/
COPY utils/ ./utils/
COPY ml/*.py ./ml/
# Models are generated at runtime (Clean Slate strategy)
RUN mkdir -p ml/models
COPY ml/models/defaults/ ./ml/models/defaults/

# Copy frontend source and build (AFTER copying backend to avoid overwriting static assets)
COPY frontend/ ./frontend/
RUN cd frontend && pnpm build

# Copy configuration templates
COPY config.default.yaml ./
COPY secrets.example.yaml ./
COPY VERSION ./
COPY ml/regions.json ./ml/regions.json

# Copy Alembic migration files for automatic database schema updates
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Copy HA Add-on entrypoint (note: path from repo root context)
COPY darkstar-dev/run.sh /run.sh
RUN chmod +x /run.sh

# Environment

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["/run.sh"]
