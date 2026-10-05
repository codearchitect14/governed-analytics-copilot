"""ASGI middleware that assigns a request id to every request and response."""

import uuid
from collections.abc import MutableMapping
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = b"x-request-id"
MAX_INCOMING_ID_LENGTH = 64


class RequestIdMiddleware:
    """Reuse a sane incoming X-Request-ID or generate one, then bind it to the log context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._incoming_request_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        await self.app(scope, receive, send_with_request_id)

    @staticmethod
    def _incoming_request_id(scope: MutableMapping[str, Any]) -> str | None:
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        for name, value in headers:
            if name == REQUEST_ID_HEADER:
                candidate = value.decode("ascii", errors="ignore")
                if (
                    0 < len(candidate) <= MAX_INCOMING_ID_LENGTH
                    and candidate.replace("-", "").isalnum()
                ):
                    return candidate
        return None
