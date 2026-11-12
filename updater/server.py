"""Minimal stdlib HTTP service: fixed operations, bearer-token auth, no caller-supplied refs."""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from .runner import run_command
from .service import ApplyBusy, ApplyRejected, Config, Updater, tree_digest
from .state import StateStore

logger = logging.getLogger("darkstar.updater")

PORT = 5001
CHECK_INTERVAL_S = 6 * 3600
FIRST_CHECK_DELAY_S = 30
MAX_BODY = 4096


def make_handler(updater: Updater, token: str) -> type[BaseHTTPRequestHandler]:
    expected = token.encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            logger.debug(format, *args)

        def _send(self, code: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            supplied = header[7:].encode() if header.startswith("Bearer ") else b""
            return hmac.compare_digest(supplied, expected)

        def _body(self) -> dict[str, Any]:
            try:
                length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return {}
            return cast("dict[str, Any]", data) if isinstance(data, dict) else {}

        def _route(self, method: str) -> None:
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            url = urlparse(self.path)
            route = (method, url.path)
            if route == ("GET", "/status"):
                self._send(200, updater.status())
            elif route == ("POST", "/check"):
                updater.check()
                self._send(200, updater.status())
            elif route == ("PUT", "/channel"):
                try:
                    updater.set_channel(str(self._body().get("channel", "")))
                except ValueError as exc:
                    self._send(400, {"error": str(exc)})
                    return
                updater.check(force=True)
                self._send(200, updater.status())
            elif route == ("POST", "/apply"):
                try:
                    updater.start_apply()
                except ApplyBusy:
                    self._send(409, {"error": "An update is already running"})
                except ApplyRejected as exc:
                    self._send(409, {"error": exc.message, "files": exc.files})
                else:
                    self._send(202, updater.status())
            elif route == ("GET", "/log"):
                try:
                    offset = int(parse_qs(url.query).get("offset", ["0"])[0])
                except ValueError:
                    offset = 0
                text, next_offset = updater.read_log(offset)
                self._send(200, {"text": text, "offset": next_offset})
            else:
                self._send(404, {"error": "not found"})

        def do_GET(self) -> None:
            self._route("GET")

        def do_POST(self) -> None:
            self._route("POST")

        def do_PUT(self) -> None:
            self._route("PUT")

    return Handler


def _background_checks(updater: Updater) -> None:
    stop = threading.Event()
    stop.wait(FIRST_CHECK_DELAY_S)
    while True:
        try:
            updater.check(force=True)
        except Exception:
            logger.exception("Scheduled update check failed")
        stop.wait(CHECK_INTERVAL_S)


def build_updater(token_env: dict[str, str] | None = None) -> Updater:
    env = token_env if token_env is not None else dict(os.environ)
    repo_dir = env["DARKSTAR_REPO_DIR"]
    config = Config(
        repo_dir=repo_dir,
        state_dir=env.get("UPDATER_STATE_DIR", "/state"),
        db_path=env.get("UPDATER_DB_PATH", "/data/planner_learning.db"),
        health_url=env.get("DARKSTAR_HEALTH_URL", "http://darkstar:5000/api/version"),
    )
    version_file = Path(repo_dir) / "VERSION"
    version = version_file.read_text().strip() if version_file.is_file() else ""
    state = StateStore(config.state_dir, "dev" if version.startswith("dev-") else "stable")
    own_dir = Path(__file__).resolve().parent
    return Updater(config, run_command, state, updater_digest=tree_digest(str(own_dir)))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("DARKSTAR_UPDATER_TOKEN", "")
    if not token:
        logger.error("DARKSTAR_UPDATER_TOKEN is empty, refusing to start")
        return 1
    if not os.environ.get("DARKSTAR_REPO_DIR"):
        logger.error("DARKSTAR_REPO_DIR is not set, refusing to start")
        return 1
    updater = build_updater()
    updater.mark_interrupted()
    threading.Thread(target=_background_checks, args=(updater,), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(updater, token))
    server.daemon_threads = True
    logger.info("Updater listening on :%d", PORT)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
