"""LLM gateway: one place for provider calls, caching, token + cost tracking."""
import hashlib
import os
import time
from collections import OrderedDict

import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field

from common.observability import instrument

app = FastAPI(title="llm-gateway")
instrument(app, "llm-gateway")

PROVIDER = os.getenv("LLM_PROVIDER", "mock")  # mock | anthropic
MODEL = os.getenv("LLM_MODEL", "claude-haiku-5-5")
# Prices are placeholders. Set the real numbers for your model via env.
PRICE_IN = float(os.getenv("PRICE_IN_PER_MTOK", "1.0"))
PRICE_OUT = float(os.getenv("PRICE_OUT_PER_MTOK", "5.0"))
CACHE_MAX = int(os.getenv("CACHE_MAX", "500"))

LLM_REQS = Counter("llm_requests_total", "LLM requests", ["provider", "cache", "caller"])
LLM_COST = Counter("llm_cost_usd_total", "Estimated LLM spend (USD)", ["caller"])
LLM_TOKENS = Counter("llm_tokens_total", "Tokens", ["direction"])
LLM_LAT = Histogram(
    "llm_provider_latency_seconds", "Provider call latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)

_cache: OrderedDict = OrderedDict()


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    system: str = ""
    max_tokens: int = Field(512, ge=1, le=4096)
    caller: str = "unknown"


class ChatResponse(BaseModel):
    text: str
    cached: bool
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _key(r: ChatRequest) -> str:
    raw = f"{MODEL}|{r.system}|{r.prompt}|{r.max_tokens}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cost(tin: int, tout: int) -> float:
    return (tin * PRICE_IN + tout * PRICE_OUT) / 1_000_000


async def _call_mock(r: ChatRequest):
    ctx = r.prompt.split("Context:", 1)[-1][:300].strip() if "Context:" in r.prompt else r.prompt[:200]
    text = f"[mock-llm] {ctx}"
    return text, max(1, len(r.prompt) // 4), max(1, len(text) // 4)


async def _call_anthropic(r: ChatRequest):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(500, "ANTHROPIC_API_KEY is not set")
    body = {"model": MODEL, "max_tokens": r.max_tokens,
            "messages": [{"role": "user", "content": r.prompt}]}
    if r.system:
        body["system"] = r.system
    async with httpx.AsyncClient(timeout=60) as c:
        resp = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json=body,
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"provider error {resp.status_code}")
    d = resp.json()
    text = "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")
    return text, d["usage"]["input_tokens"], d["usage"]["output_tokens"]


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(r: ChatRequest):
    k = _key(r)
    if k in _cache:
        _cache.move_to_end(k)
        LLM_REQS.labels(PROVIDER, "hit", r.caller).inc()
        return ChatResponse(text=_cache[k], cached=True, provider=PROVIDER,
                            input_tokens=0, output_tokens=0, cost_usd=0.0)

    start = time.perf_counter()
    text, tin, tout = await (_call_mock(r) if PROVIDER == "mock" else _call_anthropic(r))
    LLM_LAT.observe(time.perf_counter() - start)

    cost = _cost(tin, tout)
    LLM_REQS.labels(PROVIDER, "miss", r.caller).inc()
    LLM_COST.labels(r.caller).inc(cost)
    LLM_TOKENS.labels("input").inc(tin)
    LLM_TOKENS.labels("output").inc(tout)

    _cache[k] = text
    if len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return ChatResponse(text=text, cached=False, provider=PROVIDER,
                        input_tokens=tin, output_tokens=tout, cost_usd=cost)
