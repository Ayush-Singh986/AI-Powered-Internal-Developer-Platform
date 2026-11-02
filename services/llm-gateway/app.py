import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

app = FastAPI(title="LLM Gateway", version="1.0.0")
MODEL_URL = os.getenv("MODEL_SERVICE_URL", "http://model-serving:8000").rstrip("/")
TIMEOUT = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "65"))
FALLBACK_MODEL_URL = os.getenv("MODEL_FALLBACK_URL", "").rstrip("/")
GATEWAY_API_KEY = os.getenv("LLM_GATEWAY_API_KEY", "")
raw_client_keys = os.getenv("LLM_GATEWAY_CLIENT_KEYS", "")
try:
    GATEWAY_CLIENT_KEYS = json.loads(raw_client_keys) if raw_client_keys else {}
except json.JSONDecodeError as exc:
    raise RuntimeError("LLM_GATEWAY_CLIENT_KEYS must be a JSON object") from exc
if not isinstance(GATEWAY_CLIENT_KEYS, dict) or any(
    not isinstance(name, str) or not isinstance(token, str) or not token
    for name, token in GATEWAY_CLIENT_KEYS.items()
):
    raise RuntimeError("LLM_GATEWAY_CLIENT_KEYS must map caller names to non-empty tokens")
MODEL_SERVICE_API_KEY = os.getenv("MODEL_SERVICE_API_KEY", "")
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "100000"))
DATABASE_PATH = Path(os.getenv("GATEWAY_DATABASE_PATH", "/data/gateway.db"))
MAX_REQUEST_BODY_BYTES = int(os.getenv("MAX_REQUEST_BODY_BYTES", "32768"))
MAX_INPUT_BYTES = int(os.getenv("MAX_INPUT_BYTES", "16000"))
MAX_CALLS_PER_MINUTE = int(os.getenv("MAX_CALLS_PER_MINUTE", "30"))
CALLER_DAILY_TOKEN_LIMIT = int(
    os.getenv("CALLER_DAILY_TOKEN_LIMIT", str(DAILY_TOKEN_LIMIT))
)
TOKEN_USAGE_RETENTION_DAYS = int(os.getenv("TOKEN_USAGE_RETENTION_DAYS", "90"))
CACHE_TTL_SECONDS = float(os.getenv("CACHE_TTL_SECONDS", "30"))
MAX_CACHE_ENTRIES = int(os.getenv("MAX_CACHE_ENTRIES", "128"))
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
RESPONSE_CACHE: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}
CACHE_LOCK = asyncio.Lock()
if min(
    DAILY_TOKEN_LIMIT,
    CALLER_DAILY_TOKEN_LIMIT,
    MAX_REQUEST_BODY_BYTES,
    MAX_INPUT_BYTES,
    MAX_CALLS_PER_MINUTE,
    MAX_CACHE_ENTRIES,
    TOKEN_USAGE_RETENTION_DAYS,
) < 1 or CACHE_TTL_SECONDS <= 0:
    raise ValueError("Gateway limits and cache settings must be positive")


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=8192)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=32)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=2048)


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
    if not GATEWAY_API_KEY and not GATEWAY_CLIENT_KEYS:
        raise HTTPException(status_code=503, detail="LLM_GATEWAY_API_KEY is not configured")
    scheme, separator, token = (authorization or "").partition(" ")
    matching_keys = [
        key for key, value in GATEWAY_CLIENT_KEYS.items()
        if hmac.compare_digest(token, value)
    ]
    if (
        scheme.lower() != "bearer"
        or not separator
        or (not matching_keys and not (GATEWAY_API_KEY and hmac.compare_digest(token, GATEWAY_API_KEY)))
    ):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")


def caller_id_from_token(authorization: str | None) -> str:
    require_gateway_token(authorization)
    token = (authorization or "").partition(" ")[2]
    for name, configured_token in GATEWAY_CLIENT_KEYS.items():
        if hmac.compare_digest(token, configured_token):
            return name
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_usage_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS daily_token_usage (
            usage_date TEXT NOT NULL, caller_id TEXT NOT NULL,
            tokens INTEGER NOT NULL, PRIMARY KEY (usage_date, caller_id)
        )"""
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_token_usage)")}
    if "caller_id" not in columns:
        connection.execute("ALTER TABLE daily_token_usage RENAME TO daily_token_usage_legacy")
        connection.execute(
            """CREATE TABLE daily_token_usage (
                usage_date TEXT NOT NULL, caller_id TEXT NOT NULL,
                tokens INTEGER NOT NULL, PRIMARY KEY (usage_date, caller_id)
            )"""
        )
        connection.execute(
            """INSERT INTO daily_token_usage (usage_date, caller_id, tokens)
            SELECT usage_date, 'legacy', tokens FROM daily_token_usage_legacy"""
        )
        connection.execute("DROP TABLE daily_token_usage_legacy")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS token_reservations (
            id TEXT PRIMARY KEY, usage_date TEXT NOT NULL,
            caller_id TEXT NOT NULL, reserved_tokens INTEGER NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS caller_requests (
            caller_id TEXT NOT NULL, requested_at TEXT NOT NULL
        )"""
    )


def daily_token_total() -> int:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            ensure_usage_tables(connection)
            row = connection.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM daily_token_usage WHERE usage_date = ?",
                (datetime.now(timezone.utc).date().isoformat(),),
            ).fetchone()
    return int(row[0]) if row else 0


def reserve_request(caller_id: str, estimated_tokens: int) -> str | None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.execute("PRAGMA busy_timeout = 10000")
        with connection:
            ensure_usage_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(minutes=1)).isoformat()
            usage_cutoff = (
                now.date() - timedelta(days=TOKEN_USAGE_RETENTION_DAYS)
            ).isoformat()
            connection.execute(
                "DELETE FROM daily_token_usage WHERE usage_date < ?", (usage_cutoff,)
            )
            connection.execute(
                "DELETE FROM token_reservations WHERE usage_date < ?", (usage_cutoff,)
            )
            connection.execute("DELETE FROM caller_requests WHERE requested_at < ?", (cutoff,))
            call_count = connection.execute(
                "SELECT COUNT(*) FROM caller_requests WHERE caller_id = ? AND requested_at >= ?",
                (caller_id, cutoff),
            ).fetchone()[0]
            if call_count >= MAX_CALLS_PER_MINUTE:
                return None
            connection.execute(
                "INSERT INTO caller_requests (caller_id, requested_at) VALUES (?, ?)",
                (caller_id, now.isoformat()),
            )
            today = now.date().isoformat()
            totals = connection.execute(
                """SELECT
                    COALESCE(SUM(tokens), 0),
                    COALESCE(SUM(CASE WHEN caller_id = ? THEN tokens ELSE 0 END), 0)
                FROM daily_token_usage WHERE usage_date = ?""",
                (caller_id, today),
            ).fetchone()
            if totals[0] + estimated_tokens > DAILY_TOKEN_LIMIT:
                return None
            if totals[1] + estimated_tokens > CALLER_DAILY_TOKEN_LIMIT:
                return None
            connection.execute(
                """INSERT INTO daily_token_usage (usage_date, caller_id, tokens)
                VALUES (?, ?, 0) ON CONFLICT(usage_date, caller_id) DO NOTHING""",
                (today, caller_id),
            )
            reserved = connection.execute(
                """UPDATE daily_token_usage SET tokens = tokens + ?
                WHERE usage_date = ? AND caller_id = ? AND tokens + ? <= ?""",
                (estimated_tokens, today, caller_id, estimated_tokens, DAILY_TOKEN_LIMIT),
            )
            if reserved.rowcount != 1:
                return None
            reservation_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO token_reservations
                (id, usage_date, caller_id, reserved_tokens) VALUES (?, ?, ?, ?)""",
                (reservation_id, today, caller_id, estimated_tokens),
            )
    return reservation_id


def settle_reservation(reservation_id: str, actual_tokens: int | None = None) -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.execute("PRAGMA busy_timeout = 10000")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                """SELECT usage_date, caller_id, reserved_tokens
                FROM token_reservations WHERE id = ?""",
                (reservation_id,),
            ).fetchone()
            if reservation is None:
                return
            charged = reservation[2] if actual_tokens is None else max(0, actual_tokens)
            connection.execute(
                """UPDATE daily_token_usage SET tokens = MAX(0, tokens - ? + ?)
                WHERE usage_date = ? AND caller_id = ?""",
                (reservation[2], charged, reservation[0], reservation[1]),
            )
            connection.execute("DELETE FROM token_reservations WHERE id = ?", (reservation_id,))


async def cached_response(caller_id: str, request_hash: str) -> dict[str, object] | None:
    async with CACHE_LOCK:
        item = RESPONSE_CACHE.get((caller_id, request_hash))
        if item is None:
            return None
        expires_at, response = item
        if expires_at <= time.monotonic():
            del RESPONSE_CACHE[(caller_id, request_hash)]
            return None
        return json.loads(json.dumps(response))


async def cache_response(
    caller_id: str, request_hash: str, response: dict[str, object]
) -> None:
    async with CACHE_LOCK:
        current_time = time.monotonic()
        expired = [key for key, value in RESPONSE_CACHE.items() if value[0] <= current_time]
        for key in expired:
            del RESPONSE_CACHE[key]
        if len(RESPONSE_CACHE) >= MAX_CACHE_ENTRIES:
            RESPONSE_CACHE.pop(next(iter(RESPONSE_CACHE)))
        RESPONSE_CACHE[(caller_id, request_hash)] = (
            current_time + CACHE_TTL_SECONDS,
            json.loads(json.dumps(response)),
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
    request: ChatRequest,
    http_request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    caller_id = caller_id_from_token(authorization)
    content_length = http_request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body exceeds the configured size limit")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc

    request_data = request.model_dump()
    request_size = len(json.dumps(request_data, ensure_ascii=False).encode("utf-8"))
    input_size = sum(len(message.content.encode("utf-8")) for message in request.messages)
    if request_size > MAX_REQUEST_BODY_BYTES or input_size > MAX_INPUT_BYTES:
        raise HTTPException(status_code=413, detail="Prompt exceeds the configured size limit")
    request_hash = hashlib.sha256(
        json.dumps(request_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    cached = await cached_response(caller_id, request_hash)
    estimated_tokens = 0 if cached is not None else input_size + request.max_tokens
    token_reservation = reserve_request(caller_id, estimated_tokens)
    if token_reservation is None:
        BUDGET_EXCEEDED.inc()
        REQUESTS.labels(outcome="rate_or_budget_exceeded").inc()
        raise HTTPException(
            status_code=429,
            detail="Per-caller request limit or daily token budget reached",
        )
    if cached is not None:
        settle_reservation(token_reservation, 0)
        REQUESTS.labels(outcome="cache_hit").inc()
        return cached

    try:
        with LATENCY.time():
            urls = [MODEL_URL]
            if FALLBACK_MODEL_URL and FALLBACK_MODEL_URL != MODEL_URL:
                urls.append(FALLBACK_MODEL_URL)
            last_connection_error: httpx.ConnectError | None = None
            body: dict[str, object] | None = None
            for url in urls:
                for attempt in range(2):
                    try:
                        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                            response = await client.post(
                                f"{url}/v1/chat/completions",
                                json=request_data,
                                headers={"Authorization": f"Bearer {MODEL_SERVICE_API_KEY}"},
                            )
                            response.raise_for_status()
                        parsed = response.json()
                        if not isinstance(parsed, dict):
                            raise ValueError("Model service response must be a JSON object")
                        body = parsed
                        break
                    except httpx.ConnectError as exc:
                        last_connection_error = exc
                        if attempt == 0:
                            await asyncio.sleep(0.1)
                if body is not None:
                    break
            if body is None:
                raise last_connection_error or httpx.ConnectError("No model endpoint is available")
    except httpx.HTTPStatusError as exc:
        settle_reservation(token_reservation)
        REQUESTS.labels(outcome="error").inc()
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Model service returned HTTP {exc.response.status_code}",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        settle_reservation(token_reservation)
        REQUESTS.labels(outcome="error").inc()
        raise HTTPException(status_code=502, detail=f"Model service request failed: {exc}") from exc

    usage = body.get("usage")
    charged_tokens: int | None = None
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            charged_tokens = prompt_tokens + completion_tokens
            TOKENS.labels(type="input").inc(prompt_tokens)
            TOKENS.labels(type="output").inc(completion_tokens)
            if INPUT_RATE and OUTPUT_RATE:
                COST.inc(
                    prompt_tokens * float(INPUT_RATE) / 1000
                    + completion_tokens * float(OUTPUT_RATE) / 1000
                )
    settle_reservation(token_reservation, charged_tokens)
    await cache_response(caller_id, request_hash, body)
    REQUESTS.labels(outcome="success").inc()
    return body
