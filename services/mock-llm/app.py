from fastapi import FastAPI

app = FastAPI(title="Canned LLM Demo")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
def complete() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "DEMO MODE: canned answer. Inspect recent pod logs and events.",
                }
            }
        ],
        "usage": {"prompt_tokens": 24, "completion_tokens": 12, "total_tokens": 36},
    }
