"""Run the telemetry receiver as a single Uvicorn process."""

from __future__ import annotations

import os

import uvicorn

from telemetry_receiver.app import app


def main() -> None:
    host = os.environ.get("TELEMETRY_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("TELEMETRY_PORT", "8765"))
    except ValueError as exc:
        raise SystemExit("TELEMETRY_PORT must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("TELEMETRY_PORT must be an integer from 1 to 65535")
    uvicorn.run(app, host=host, port=port, access_log=False, log_level="info")


if __name__ == "__main__":
    main()
