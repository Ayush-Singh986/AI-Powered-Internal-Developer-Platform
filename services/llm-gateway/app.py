import hmac
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

app = FastAPI(title="LLM Gateway", version="1.0.0")
MODEL_URL = os.getenv("MODEL_SERVICE_URL", "http://model-serving:8000").rstrip("/")
TIMEOUT = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "65"))
GATEWAY_API_KEY = os.getenv("SERVICE_AUTH_TOKEN") or os.getenv("LLM_GATEWAY_API_KEY", "")
MODEL_SERVICE_API_KEY = os.getenv("SERVICE_AUTH_TOKEN") or os.getenv("MODEL_SERVICE_API_KEY", "")
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "100000"))
DATABASE_PATH = Path(os.getenv("GATEWAY_DATABASE_PATH", "/data/gateway.db"))
REQUESTS = Counter("llm_gateway_requests_total", "Gateway requests", ["outcome"])
TOKENS = Counter("llm_tokens_total", "Tokens reported by the model provider", ["type"])
COST = Counter("llm_cost_usd_total", "Estimated cost using configured provider rates")
RATES_CONFIGURED = Gauge(
    "llm_cost_rates_configured", "Whether both provider-specific token rates are configured"
)
BUDGET_EXCEEDED = Counter(
    "llm_budget_exceeded_total", "Requests rejected because the UTC daily token budget was reached"
)
LATENCY = Histogram("llm_request_duration_seconds", "End-to-end gateway request latency")
HTTP_REQUESTS = Counter("gateway_http_requests_total", "HTTP requests", ["method", "status"])
HTTP_LATENCY = Histogram("gateway_http_request_duration_seconds", "HTTP request latency")
INPUT_RATE = os.getenv("INPUT_COST_PER_1K_TOKENS_USD")
OUTPUT_RATE = os.getenv("OUTPUT_COST_PER_1K_TOKENS_USD")
RATES_CONFIGURED.set(1 if INPUT_RATE and OUTPUT_RATE else 0)


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


def require_gateway_token(authorization: str | None) -> None:
    if not GATEWAY_API_KEY:
        raise HTTPException(status_code=503, detail="LLM_GATEWAY_API_KEY is not configured")
    scheme, separator, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not separator or not hmac.compare_digest(token, GATEWAY_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")


def daily_token_total() -> int:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS daily_token_usage (
                    usage_date TEXT PRIMARY KEY, tokens INTEGER NOT NULL
                )"""
            )
            row = connection.execute(
                "SELECT tokens FROM daily_token_usage WHERE usage_date = ?",
                (datetime.now(timezone.utc).date().isoformat(),),
            ).fetchone()
    return int(row[0]) if row else 0


def record_daily_tokens(tokens: int) -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS daily_token_usage (
                    usage_date TEXT PRIMARY KEY, tokens INTEGER NOT NULL
                )"""
            )
            connection.execute(
                """INSERT INTO daily_token_usage (usage_date, tokens) VALUES (?, ?)
                ON CONFLICT(usage_date) DO UPDATE SET tokens = tokens + excluded.tokens""",
                (datetime.now(timezone.utc).date().isoformat(), tokens),
            )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/dependencies/model-serving")
async def model_dependency_health(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    require_gateway_token(authorization)
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(
                f"{MODEL_URL}/health",
                headers={"Authorization": f"Bearer {MODEL_SERVICE_API_KEY}"},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return {"status": "unavailable"}
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat/completions")
async def chat(
    request: ChatRequest, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    require_gateway_token(authorization)
    if daily_token_total() >= DAILY_TOKEN_LIMIT:
        BUDGET_EXCEEDED.inc()
        REQUESTS.labels(outcome="budget_exceeded").inc()
        raise HTTPException(status_code=429, detail="Daily LLM token limit reached")
    try:
        with LATENCY.time():
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    f"{MODEL_URL}/v1/chat/completions",
                    json=request.model_dump(),
                    headers={"Authorization": f"Bearer {MODEL_SERVICE_API_KEY}"},
                )
                response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        REQUESTS.labels(outcome="error").inc()
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Model service returned HTTP {exc.response.status_code}",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        REQUESTS.labels(outcome="error").inc()
        raise HTTPException(status_code=502, detail=f"Model service request failed: {exc}") from exc

    usage = body.get("usage")
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            TOKENS.labels(type="input").inc(prompt_tokens)
            TOKENS.labels(type="output").inc(completion_tokens)
            record_daily_tokens(prompt_tokens + completion_tokens)
            if INPUT_RATE and OUTPUT_RATE:
                COST.inc(
                    prompt_tokens * float(INPUT_RATE) / 1000
                    + completion_tokens * float(OUTPUT_RATE) / 1000
                )
    REQUESTS.labels(outcome="success").inc()
    return body
