import json

import pytest

from app.ws import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail_on_send: bool = False):
        self.sent: list[str] = []
        self.accepted = False
        self.fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        if self.fail_on_send:
            raise RuntimeError("client disconnected")
        self.sent.append(text)


async def test_connect_accepts_and_registers():
    m = ConnectionManager()
    ws = FakeWebSocket()
    await m.connect(ws)
    assert ws.accepted
    assert m.client_count == 1


async def test_broadcast_fans_out_to_all_clients():
    m = ConnectionManager()
    a, b = FakeWebSocket(), FakeWebSocket()
    await m.connect(a)
    await m.connect(b)

    await m.broadcast({"type": "reading", "sensor_id": "x", "ts": 1})

    expected = json.dumps({"type": "reading", "sensor_id": "x", "ts": 1})
    assert a.sent == [expected]
    assert b.sent == [expected]


async def test_broadcast_drops_dead_clients():
    m = ConnectionManager()
    good = FakeWebSocket()
    bad = FakeWebSocket(fail_on_send=True)
    await m.connect(good)
    await m.connect(bad)

    await m.broadcast({"x": 1})
    assert m.client_count == 1
    assert len(good.sent) == 1

    await m.broadcast({"y": 2})
    assert len(good.sent) == 2


async def test_disconnect_removes_client():
    m = ConnectionManager()
    ws = FakeWebSocket()
    await m.connect(ws)
    m.disconnect(ws)
    assert m.client_count == 0

    await m.broadcast({"x": 1})
    assert ws.sent == []
