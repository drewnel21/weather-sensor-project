import json
import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def send_text(self, data: str) -> None: ...


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocketLike] = set()

    async def connect(self, ws: WebSocketLike) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocketLike) -> None:
        self._clients.discard(ws)

    async def broadcast(self, event: dict[str, Any]) -> None:
        msg = json.dumps(event)
        dead: list[WebSocketLike] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(msg)
            except Exception as e:
                log.debug("Dropping dead WS client: %s", e)
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)
