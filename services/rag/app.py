import os
import hmac
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

app = FastAPI(title="RAG Service", version="1.0.0")
REQUESTS = Counter("rag_retrieval_requests_total", "Retrieval requests")
HTTP_REQUESTS = Counter("rag_http_requests_total", "HTTP requests", ["method", "status"])
HTTP_LATENCY = Histogram("rag_http_request_duration_seconds", "HTTP request latency")
DOCS_DIR = Path(os.getenv("DOCUMENTS_PATH", str(Path(__file__).parent / "runbooks")))
SERVICE_API_KEY = os.getenv("SERVICE_AUTH_TOKEN") or os.getenv("SERVICE_API_KEY", "")


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=3, ge=1, le=10)


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


def load_documents() -> list[dict[str, str]]:
    if not DOCS_DIR.is_dir():
        raise RuntimeError(f"Documents directory does not exist: {DOCS_DIR}")
    return [
        {"id": path.name, "text": path.read_text(encoding="utf-8")}
        for path in sorted(DOCS_DIR.glob("*.md"))
    ]


def require_service_token(authorization: str | None) -> None:
    if not SERVICE_API_KEY:
        raise HTTPException(status_code=503, detail="SERVICE_AUTH_TOKEN is not configured")
    scheme, separator, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not separator or not hmac.compare_digest(token, SERVICE_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/retrieve")
def retrieve(
    request: RetrievalRequest, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    require_service_token(authorization)
    REQUESTS.inc()
    terms = {term.casefold() for term in request.query.split() if len(term) > 2}
    try:
        documents = load_documents()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    ranked = []
    for document in documents:
        text = document["text"]
        score = sum(text.casefold().count(term) for term in terms)
        if score:
            ranked.append({"id": document["id"], "text": text, "score": score})
    ranked.sort(key=lambda result: (-int(result["score"]), str(result["id"])))
    return {"results": ranked[: request.limit], "count": min(len(ranked), request.limit)}
