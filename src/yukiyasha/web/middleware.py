"""HTTP safety middleware for the local Yukiyasha API."""

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class RequestBodyLimitMiddleware:
    """Reject request bodies before application-level parsing exceeds the configured limit."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
                await response(scope, receive, send)
                return

        messages: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break

            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> dict[str, Any]:
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)

    async def _reject(
        self, scope: dict[str, Any], receive: Receive, send: Send
    ) -> None:
        response = JSONResponse({"detail": "Request body too large"}, status_code=413)
        await response(scope, receive, send)


CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)
# Swagger UI loads its assets from a CDN and uses inline scripts, so it gets no CSP.
NO_CSP_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware:
    """Add browser hardening headers and cache rules to every HTTP response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])]
                present = {k.lower() for k, _ in headers}

                def add(name: bytes, value: str) -> None:
                    if name not in present:
                        headers.append((name, value.encode("latin-1")))

                add(b"x-content-type-options", "nosniff")
                add(b"x-frame-options", "DENY")
                add(b"referrer-policy", "no-referrer")
                if not path.startswith(NO_CSP_PATHS):
                    add(b"content-security-policy", CONTENT_SECURITY_POLICY)
                if path.startswith("/api/"):
                    add(b"cache-control", "no-store")  # responses can contain file content
                else:
                    add(b"cache-control", "no-cache")  # revalidate: UI files change on upgrade
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
