"""Home Assistant history client optimized for simulator reuse."""

import json
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import websockets

from inputs import load_home_assistant_config


def _ensure_iso(dt: datetime) -> str:
    """Return a UTC ISO timestamp for the provided datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class HomeAssistantHistoryClient:
    """WebSocket client that reuses historical statistic queries with a simple cache."""

    def __init__(self, cache_dir: str | Path = "data/cache"):
        self._config = load_home_assistant_config() or {}
        self._token = self._config.get("token")
        base_url = (self._config.get("url") or "").rstrip("/")
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._ws_url: Optional[str] = None
        self._use_ssl = False
        if base_url.startswith("https://"):
            self._ws_url = base_url.replace("https://", "wss://") + "/api/websocket"
            self._use_ssl = True
        elif base_url.startswith("http://"):
            self._ws_url = base_url.replace("http://", "ws://") + "/api/websocket"
        self.enabled = bool(self._ws_url and self._token)

    def _cache_path(self, entity_id: str, start_time: datetime) -> Path:
        date_key = start_time.date().isoformat()
        sanitized = entity_id.replace(".", "_").replace("/", "_")
        return self._cache_dir / f"{sanitized}_{date_key}.json"

    def _load_cached(
        self,
        path: Path,
        start_iso: str,
        end_iso: str,
        period: str,
    ) -> Optional[List[Dict[str, Any]]]:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if (
            payload.get("start_time") == start_iso
            and payload.get("end_time") == end_iso
            and payload.get("period") == period
        ):
            return payload.get("result")
        return None

    def _write_cache(
        self,
        path: Path,
        entity_id: str,
        start_iso: str,
        end_iso: str,
        period: str,
        result: List[Dict[str, Any]],
    ) -> None:
        payload = {
            "entity_id": entity_id,
            "start_time": start_iso,
            "end_time": end_iso,
            "period": period,
            "result": result,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    async def fetch_statistics(
        self,
        entity_id: str,
        start_time: datetime,
        end_time: datetime,
        period: str = "hour",
    ) -> List[Dict[str, Any]]:
        """
        Fetch LTS statistics from Home Assistant for a single entity.

        Caches the response so repeated historical runs reuse the saved JSON.
        """
        if not self.enabled:
            return []
        start_iso = _ensure_iso(start_time)
        end_iso = _ensure_iso(end_time)
        cache_path = self._cache_path(entity_id, start_time)
        cached = self._load_cached(cache_path, start_iso, end_iso, period)
        if cached is not None:
            return cached

        try:
            ssl_context = None
            if self._use_ssl:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            async with websockets.connect(self._ws_url, ssl=ssl_context) as websocket:
                # Handle authentication handshake
                initial = json.loads(await websocket.recv())
                if initial.get("type") == "auth_required":
                    await websocket.send(json.dumps({"type": "auth", "access_token": self._token}))
                    auth_response = json.loads(await websocket.recv())
                    if auth_response.get("type") != "auth_ok":
                        raise RuntimeError(f"HA auth failed: {auth_response}")

                request_id = 1
                payload = {
                    "id": request_id,
                    "type": "recorder/statistics_during_period",
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "statistic_ids": [entity_id],
                    "period": period,
                }
                await websocket.send(json.dumps(payload))

                while True:
                    raw = await websocket.recv()
                    message = json.loads(raw)
                    if message.get("id") != request_id:
                        continue
                    result = message.get("result", {})
                    entity_data = result.get(entity_id, [])
                    self._write_cache(
                        cache_path, entity_id, start_iso, end_iso, period, entity_data
                    )
                    return entity_data
        except Exception:
            return []
