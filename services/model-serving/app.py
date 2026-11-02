import hmac
import os
import time

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

app = FastAPI(title="Model Serving Adapter", version="1.0.0")
REQUESTS = Counter("model_requests_total", "Model requests", ["outcome"])
LATENCY = Histogram("model_request_duration_seconds", "Model request latency")
HTTP_REQUESTS = Counter("model_http_requests_total", "HTTP requests", ["method", "status"])
HTTP_LATENCY = Histogram("model_http_request_duration_seconds", "HTTP request latency")
BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
SERVICE_API_KEY = os.getenv("SERVICE_AUTH_TOKEN") or os.getenv("MODEL_SERVICE_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))


class ChatRequest(BaseModel):
    messages: list[dict[str, str]] = Field(min_length=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=8192)


@app.middleware("http")
async def instrument_http(request: Request, call_next):
    status_code = 500
    started = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        HTTP_REQUESTS.labels(method=request.method, status=str(status_code)).inc()
        HTTP_LATENCY.observe(time.perf_counter() - started)


def require_service_token(authorization: str | None) -> None:
    if not SERVICE_API_KEY:
        raise HTTPException(status_code=503, detail="MODEL_SERVICE_API_KEY is not configured")
    scheme, separator, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not separator or not hmac.compare_digest(token, SERVICE_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat/completions")
async def chat(
    request: ChatRequest, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    require_service_token(authorization)
    if not BASE_URL:
        raise HTTPException(status_code=503, detail="LLM_BASE_URL is not configured")
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    payload = {
        "model": MODEL,
        "messages": request.messages,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    try:
        with LATENCY.time():
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    f"{BASE_URL}/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        REQUESTS.labels(outcome="error").inc()
        raise HTTPException(
            status_code=502, detail=f"LLM provider returned HTTP {exc.response.status_code}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        REQUESTS.labels(outcome="error").inc()
        raise HTTPException(status_code=502, detail=f"LLM provider request failed: {exc}") from exc
    REQUESTS.labels(outcome="success").inc()
    return body
