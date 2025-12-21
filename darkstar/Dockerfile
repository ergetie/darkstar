# Darkstar Energy Manager - Home Assistant Add-on Dockerfile
# Built for multi-arch (amd64, arm64)
# Build context is repo root

FROM python:3.12-alpine

# Enable community repository for GLPK
RUN echo "https://dl-cdn.alpinelinux.org/alpine/v3.21/community" >> /etc/apk/repositories

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-numpy \
    py3-pandas \
    nodejs \
    npm \
    curl \
    jq \
    bash \
    # GLPK solver for PuLP (Kepler optimizer) - from community repo
    glpk \
    # Build dependencies for lightgbm
    gcc \
    g++ \
    musl-dev \
    python3-dev \
    cmake \
    make \
    libgomp

WORKDIR /app

# Install pnpm and build frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN npm install -g pnpm && cd frontend && pnpm install --frozen-lockfile

COPY frontend/ ./frontend/
RUN cd frontend && pnpm build

# Install Python dependencies
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY planner/ ./planner/
COPY executor/ ./executor/
COPY bin/ ./bin/
COPY ml/*.py ./ml/
COPY ml/models/*.lgb ./ml/models/
COPY inputs.py db_writer.py ./

# Copy configuration templates
COPY config.default.yaml ./
COPY secrets.example.yaml ./

# Copy HA Add-on entrypoint (note: path from repo root context)
COPY darkstar/run.sh /run.sh
RUN chmod +x /run.sh

# Environment
ENV FLASK_APP=backend.webapp
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

CMD ["/run.sh"]
