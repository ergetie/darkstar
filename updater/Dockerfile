# Darkstar updater sidecar. Build context is the repository root:
#   docker compose build updater
FROM python:3.12-slim

# Docker CLI + compose plugin only (the daemon is the host's, via the mounted socket).
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:27-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/darkstar
COPY updater/ ./updater/
RUN chmod +x /opt/darkstar/updater/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/opt/darkstar/updater/entrypoint.sh"]
