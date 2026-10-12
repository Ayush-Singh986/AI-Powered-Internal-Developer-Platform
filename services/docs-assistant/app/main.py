"""RAG docs assistant: TF-IDF retrieval over markdown + answer via llm-gateway."""
import os
import pathlib

import httpx
from fastapi import FastAPI
from prometheus_client import Counter
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from common.observability import instrument

app = FastAPI(title="docs-assistant")
instrument(app, "docs-assistant")

DOCS_DIR = pathlib.Path(os.getenv("DOCS_DIR", pathlib.Path(__file__).parent.parent / "docs"))
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://llm-gateway:8000")
ANSWERS = Counter("docs_answers_total", "Answers", ["answered_by"])

_chunks: list = []
_vec = None
_matrix = None


def build_index():
    global _vec, _matrix
    _chunks.clear()
    for f in sorted(DOCS_DIR.glob("*.md")):
        for part in f.read_text().split("\n## "):
            part = part.strip()
            if len(part) > 40:
                _chunks.append({"file": f.name, "text": part})
    if _chunks:
        _vec = TfidfVectorizer(stop_words="english")
        _matrix = _vec.fit_transform([c["text"] for c in _chunks])


build_index()


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@app.post("/ask")
async def ask(a: Ask):
    if not _chunks:
        return {"answer": "No docs indexed.", "sources": [], "llm_used": False}
    scores = cosine_similarity(_vec.transform([a.question]), _matrix)[0]
    top = scores.argsort()[::-1][:3]
    hits = [(int(i), float(scores[i])) for i in top if scores[i] > 0]
    sources = [{"file": _chunks[i]["file"], "score": round(s, 3)} for i, s in hits]
    if not hits:
        ANSWERS.labels("no_match").inc()
        return {"answer": "I could not find this in the docs.", "sources": [], "llm_used": False}

    context = "\n\n---\n\n".join(_chunks[i]["text"] for i, _ in hits)
    prompt = (f"Answer using ONLY the context. If it is not there, say so.\n\n"
              f"Context:\n{context}\n\nQuestion: {a.question}")
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(f"{GATEWAY_URL}/v1/chat",
                             json={"prompt": prompt, "caller": "docs-assistant", "max_tokens": 400})
        r.raise_for_status()
        ANSWERS.labels("llm").inc()
        return {"answer": r.json()["text"], "sources": sources, "llm_used": True}
    except Exception:
        ANSWERS.labels("fallback").inc()  # gateway down: still return the best chunk
        return {"answer": _chunks[hits[0][0]]["text"][:600], "sources": sources, "llm_used": False}
