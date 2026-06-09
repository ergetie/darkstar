import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.ha_socket import HAWebSocketClient

CONFIG = {
    "input_sensors": {
        "battery_soc": "sensor.soc",
        "pv_power": "sensor.pv",
    },
    "system": {"grid_meter_type": "net"},
}


class FakeWebSocket:
    def __init__(self, messages: list[dict[str, object]], client: HAWebSocketClient):
        self.messages = [json.dumps(message) for message in messages]
        self.client = client
        self.sent: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, payload: str):
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        if not self.messages:
            self.client.running = False
            return json.dumps({"type": "noop"})
        return self.messages.pop(0)


def make_client() -> HAWebSocketClient:
    with (
        patch(
            "backend.ha_socket.load_home_assistant_config",
            return_value={"url": "http://ha.local", "token": "token"},
        ),
        patch("backend.ha_socket.load_yaml", return_value=CONFIG),
    ):
        return HAWebSocketClient()


def test_monitored_entities_are_loaded_from_config():
    client = make_client()

    assert client.url == "ws://ha.local/api/websocket"
    assert client.token == "token"
    assert client.monitored_entities == {"sensor.soc": "soc", "sensor.pv": "pv_kw"}


@pytest.mark.asyncio
async def test_connect_authenticates_subscribes_and_handles_messages():
    client = make_client()
    client.running = True
    messages = [
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {
            "id": 2,
            "type": "result",
            "result": [
                {"entity_id": "sensor.soc", "state": "55", "attributes": {"unit_of_measurement": "%"}}
            ],
        },
        {
            "type": "event",
            "event": {
                "event_type": "state_changed",
                "data": {
                    "entity_id": "sensor.pv",
                    "new_state": {"state": "1200", "attributes": {"unit_of_measurement": "W"}},
                },
            },
        },
    ]
    fake_ws = FakeWebSocket(messages, client)

    with (
        patch("backend.ha_socket.websockets.connect", return_value=fake_ws),
        patch("backend.events.emit_live_metrics") as emit_live_metrics,
    ):
        await client.connect()

    assert fake_ws.sent[0] == {"type": "auth", "access_token": "token"}
    assert fake_ws.sent[1]["type"] == "subscribe_events"
    assert fake_ws.sent[2] == {"id": 2, "type": "get_states"}
    assert {"soc": 55.0} in [call.args[0] for call in emit_live_metrics.call_args_list]
    assert {"pv_kw": 1.2} in [call.args[0] for call in emit_live_metrics.call_args_list]
    assert client.stats["messages_received"] >= 3
    assert client.stats["metrics_emitted"] == 2


@pytest.mark.asyncio
async def test_connect_retries_after_socket_error():
    client = make_client()
    client.running = True
    fake_ws = FakeWebSocket(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
        ],
        client,
    )

    with (
        patch(
            "backend.ha_socket.websockets.connect",
            side_effect=[RuntimeError("boom"), fake_ws],
        ) as connect,
        patch("backend.ha_socket.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        await client.connect()

    assert connect.call_count == 2
    sleep.assert_awaited_once_with(5)
