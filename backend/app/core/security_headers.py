"""Security headers for every response."""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: https://*.tile.openstreetmap.org; "
    "connect-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src 'self' https://fonts.gstatic.com; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
}


async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response
