import time
from collections import defaultdict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects enterprise security headers into every HTTP response.
    Protects against XSS, clickjacking, MIME-type sniffing, and data leakage.
    """
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Standard OWASP security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        
        # Clickjacking defense with embed allowance for the customer widget
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data:; "
            "frame-ancestors 'self' *; "
            "object-src 'none';"
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    In-memory sliding window rate limiter to defend against brute force,
    credential stuffing, and Denial of Service (DoS) attempts.
    """
    def __init__(self, app, max_requests_per_minute: int = 150):
        super().__init__(app)
        self.max_requests = max_requests_per_minute
        # ip -> list of timestamps
        self.request_history = defaultdict(list)
        # Auth specific rate limit: 20 per minute
        self.auth_history = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Whitelist static docs, openapi, and health checks
        path = request.url.path
        if path in ("/docs", "/openapi.json", "/redoc", "/api/v1/health", "/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - 60.0  # 1 minute sliding window

        # Check strict auth endpoints
        if "/auth/login" in path or "/auth/register" in path or "/auth/invitations/" in path:
            recent_auth = [t for t in self.auth_history[client_ip] if t > window_start]
            if len(recent_auth) >= 25:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many authentication attempts. Please retry after 1 minute."},
                    headers={"Retry-After": "60"}
                )
            recent_auth.append(now)
            self.auth_history[client_ip] = recent_auth

        # General rate limiting
        recent_requests = [t for t in self.request_history[client_ip] if t > window_start]
        if len(recent_requests) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "API rate limit exceeded. Please slow down your requests."},
                headers={"Retry-After": "60"}
            )
        recent_requests.append(now)
        self.request_history[client_ip] = recent_requests

        return await call_next(request)


class AttachmentBodyLimitMiddleware:
    """Bound attachment multipart bytes before Starlette can spool the body to disk."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        import re
        from app.helpdesk.attachment_storage import MAX_BODY_BYTES
        if scope["type"] != "http" or scope["method"] != "POST" or not re.fullmatch(
                r"/api/v1/helpdesk/(?:my-tickets|tickets)/[^/]+/attachments", scope["path"]):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return await JSONResponse({"detail": "附件请求超过大小限制"}, status_code=413)(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > MAX_BODY_BYTES:
                return await JSONResponse({"detail": "附件请求超过大小限制"}, status_code=413)(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()
        await self.app(scope, bounded_receive, send)
