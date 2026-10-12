"""AIOps agent: watches Prometheus, opens incidents, restarts bad deployments (opt-in)."""
import asyncio
import math
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter
from pydantic import BaseModel

from common.observability import instrument

PROM_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://llm-gateway:8000")
ENABLE_REMEDIATION = os.getenv("ENABLE_REMEDIATION", "false").lower() == "true"
INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))
COOLDOWN = int(os.getenv("COOLDOWN_SECONDS", "300"))

# service name (metric label) -> (namespace, deployment). The agent never touches itself or the portal.
TARGETS = {
    "docs-assistant": ("docs-assistant", "docs-assistant"),
    "model-serving": ("model-serving", "model-serving"),
    "llm-gateway": ("llm-gateway", "llm-gateway"),
}
RULES = [
    {
        "name": "high_error_rate",
        "query": 'sum by (service)(rate(http_requests_total{status=~"5.."}[2m])) '
                 "/ sum by (service)(rate(http_requests_total[2m]))",
        "threshold": 0.2,
    },
    {
        "name": "high_p95_latency",
        "query": "histogram_quantile(0.95, sum by (service, le)"
                 "(rate(http_request_duration_seconds_bucket[2m])))",
        "threshold": 3.0,
    },
]

INCIDENTS = Counter("aiops_incidents_total", "Incidents", ["rule", "action"])
incidents: deque = deque(maxlen=100)
_last_action: dict = {}


async def summarize(service, rule, value):
    fallback = f"{service} breached {rule} (value {value:.2f})."
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{GATEWAY_URL}/v1/chat", json={
                "prompt": f"Write one short sentence for an incident feed. Service: {service}. "
                          f"Rule: {rule}. Value: {value:.2f}.",
                "caller": "aiops-agent", "max_tokens": 80})
        r.raise_for_status()
        text = r.json()["text"].strip()
        return fallback if text.startswith("[mock-llm]") else text
    except Exception:
        return fallback


def _restart(namespace: str, deployment: str):
    from kubernetes import client, config
    config.load_incluster_config()
    patch = {"spec": {"template": {"metadata": {"annotations": {
        "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()}}}}}
    client.AppsV1Api().patch_namespaced_deployment(deployment, namespace, patch)


async def handle(service: str, rule: str, value: float):
    now = time.time()
    if service not in TARGETS:
        action = "ignored_unmanaged"
    elif now - _last_action.get(service, 0) < COOLDOWN:
        action = "skipped_cooldown"
    elif not ENABLE_REMEDIATION:
        action = "dry_run"
        _last_action[service] = now
    else:
        try:
            ns, dep = TARGETS[service]
            await asyncio.to_thread(_restart, ns, dep)
            action = "restarted"
        except Exception:
            action = "failed"
        _last_action[service] = now
    INCIDENTS.labels(rule, action).inc()
    incidents.appendleft({
        "id": uuid.uuid4().hex[:8],
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "service": service, "rule": rule, "value": round(value, 3),
        "action": action, "summary": await summarize(service, rule, value),
    })


async def check_once():
    async with httpx.AsyncClient(timeout=10) as c:
        for rule in RULES:
            try:
                r = await c.get(f"{PROM_URL}/api/v1/query", params={"query": rule["query"]})
                results = r.json()["data"]["result"]
            except Exception:
                continue
            for item in results:
                value = float(item["value"][1])
                svc = item["metric"].get("service")
                if svc and not math.isnan(value) and value > rule["threshold"]:
                    await handle(svc, rule["name"], value)


async def loop():
    while True:
        await check_once()
        await asyncio.sleep(INTERVAL)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="aiops-agent", lifespan=lifespan)
instrument(app, "aiops-agent")


@app.get("/incidents")
def list_incidents():
    return {"remediation_enabled": ENABLE_REMEDIATION, "incidents": list(incidents)}


class Simulate(BaseModel):
    service: str = "docs-assistant"
    rule: str = "high_error_rate"
    value: float = 0.5


@app.post("/simulate")
async def simulate(s: Simulate):
    if s.rule not in {r["name"] for r in RULES}:
        raise HTTPException(400, "unknown rule")
    await handle(s.service, s.rule, s.value)
    return incidents[0]
