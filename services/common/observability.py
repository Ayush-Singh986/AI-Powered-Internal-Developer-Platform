"""Shared metrics + health endpoints. Every service calls instrument(app, name)."""
import time

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQS = Counter("http_requests_total", "HTTP requests", ["service", "method", "path", "status"])
LAT = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
_SKIP = {"/metrics", "/healthz"}


def instrument(app, service: str):
    @app.middleware("http")
    async def _metrics(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            route = request.scope.get("route")
            path = route.path if route else request.url.path
            if path not in _SKIP:
                REQS.labels(service, request.method, path, str(status)).inc()
                LAT.labels(service, path).observe(time.perf_counter() - start)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "service": service}
