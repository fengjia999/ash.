"""Compress dashboard text without buffering chat streams or binary assets."""

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder


class _DashboardGZipResponder(GZipResponder):
    bypass = False

    async def send_with_gzip(self, message):
        if message["type"] == "http.response.start":
            headers = Headers(raw=message["headers"])
            content_type = headers.get("content-type", "").split(";", 1)[0]
            self.bypass = (
                content_type == "text/event-stream"
                or "no-transform" in headers.get("cache-control", "")
                or not (
                    content_type.startswith("text/")
                    or content_type in {"application/json", "application/javascript"}
                )
            )
        if self.bypass:
            await self.send(message)
        else:
            await super().send_with_gzip(message)


class DashboardGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        eligible = (
            scope["type"] == "http"
            and scope.get("method") == "GET"
            and (
                path.startswith(("/static/", "/api/"))
                or path in {"/dashboard", "/context", "/prompt"}
            )
        )
        if eligible and "gzip" in Headers(scope=scope).get("accept-encoding", ""):
            responder = _DashboardGZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
            await responder(scope, receive, send)
        else:
            await self.app(scope, receive, send)
