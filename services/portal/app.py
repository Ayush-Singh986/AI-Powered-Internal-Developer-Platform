"""Web console and same-origin API for the internal developer platform."""
import asyncio
import hmac
import json
import os
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

SERVICE_NAMES = ("docs-assistant", "model-serving", "llm-gateway", "aiops-agent")
SERVICE_KEYS = {
    "docs-assistant": "docs",
    "model-serving": "model",
    "llm-gateway": "gateway",
    "aiops-agent": "aiops",
}
DEFAULT_DEV = {
    "services": {
        "docs": os.getenv("DOCS_URL", "http://docs-assistant:8000"),
        "model": os.getenv("MODEL_URL", "http://model-serving:8000"),
        "gateway": os.getenv("GATEWAY_URL", "http://llm-gateway:8000"),
        "aiops": os.getenv("AIOPS_URL", "http://aiops-agent:8000"),
    },
    "prometheus": os.getenv("PROMETHEUS_URL", "http://prometheus:9090"),
    "grafana": os.getenv("GRAFANA_URL", "http://localhost:3000"),
    "namespaces": {},
}
DOCKER_API_URL = os.getenv("DOCKER_API_URL", "").rstrip("/")
COMPOSE_PROJECT = os.getenv("COMPOSE_PROJECT_NAME", "ai-idp")
OPS_API_TOKEN = os.getenv("OPS_API_TOKEN", "")
WEB_ROOT = Path(__file__).parent / "web" / "dist"


def load_environments() -> dict:
    raw = os.getenv("IDP_ENVIRONMENTS", "").strip()
    if not raw:
        return {"dev": DEFAULT_DEV}
    try:
        environments = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("IDP_ENVIRONMENTS must be valid JSON") from exc
    if not isinstance(environments, dict):
        raise RuntimeError("IDP_ENVIRONMENTS must be a JSON object")
    return environments


ENVIRONMENTS = load_environments()
app = FastAPI(title="AI IDP Console", version="1.0.0")


def get_environment(name: str) -> dict:
    environment = ENVIRONMENTS.get(name)
    if not isinstance(environment, dict) or not isinstance(environment.get("services"), dict):
        raise HTTPException(404, "Environment is not configured")
    return environment


async def get_json(url: str, *, params: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "The connected platform service did not respond")


async def forward(environment: str, service_key: str, path: str, *, payload: dict | None = None):
    config = get_environment(environment)
    base_url = config["services"].get(service_key)
    if not base_url:
        raise HTTPException(503, "This service is not configured for the selected environment")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(
                "POST" if payload is not None else "GET",
                f"{base_url.rstrip('/')}/{path.lstrip('/')}",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "The platform service rejected the request")
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "The connected platform service did not respond")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "portal"}


@app.get("/api/config")
def config():
    available = []
    for name in ("dev", "staging", "production"):
        current = ENVIRONMENTS.get(name)
        available.append({
            "name": name,
            "configured": isinstance(current, dict) and bool(current.get("services")),
            "label": name.title() if name != "production" else "Production",
        })
    return {
        "environments": available,
        "docker_logs": bool(DOCKER_API_URL and OPS_API_TOKEN),
        "ops_access_required": True,
    }


def require_ops_access(request: Request):
    if not OPS_API_TOKEN:
        raise HTTPException(503, "Operations access is disabled until OPS_API_TOKEN is configured")
    provided = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not hmac.compare_digest(provided, OPS_API_TOKEN):
        raise HTTPException(401, "A valid operations access token is required")


async def kube_get(namespace: str, resource_path: str, params: dict | None = None):
    token_path = Path(os.getenv("KUBERNETES_TOKEN_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/token"))
    ca_path = Path(os.getenv("KUBERNETES_CA_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"))
    host = os.getenv("KUBERNETES_SERVICE_HOST", "")
    port = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    if not host or not token_path.is_file():
        raise HTTPException(503, "In-cluster Kubernetes read-only access is not available")
    try:
        token = token_path.read_text().strip()
        async with httpx.AsyncClient(
            verify=str(ca_path) if ca_path.is_file() else True,
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        ) as client:
            response = await client.get(
                f"https://{host}:{port}/api/v1/namespaces/{namespace}/{resource_path.lstrip('/')}",
                params=params,
            )
            response.raise_for_status()
            return response
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Kubernetes denied the read-only request")
    except httpx.HTTPError:
        raise HTTPException(502, "Kubernetes API could not be reached")


async def kube_containers(environment: dict) -> dict:
    namespaces = environment.get("namespaces", {})
    if not namespaces:
        return {"configured": False, "containers": [], "message": "No Kubernetes workload namespaces are mapped for this environment."}

    async def list_service_pods(service: str, namespace: str):
        selector = environment.get("workload_labels", {}).get(service, f"app={service}")
        response = await kube_get(namespace, "pods", {"labelSelector": selector})
        rows = []
        for pod in response.json().get("items", []):
            pod_status = pod.get("status", {})
            phase = pod_status.get("phase", "Unknown").lower()
            for container in pod_status.get("containerStatuses", []):
                rows.append({
                    "id": pod.get("metadata", {}).get("name", ""),
                    "name": f"{pod.get('metadata', {}).get('name', '')}/{container.get('name', '')}",
                    "service": service,
                    "state": "running" if container.get("ready") else phase,
                    "status": f"{container.get('restartCount', 0)} restarts · {container.get('image', '').split('/')[-1]}",
                })
        return rows

    results = await asyncio.gather(*(list_service_pods(service, namespace) for service, namespace in namespaces.items()))
    return {"configured": True, "containers": [row for group in results for row in group], "message": "Read-only Kubernetes pod inventory."}


@app.get("/api/overview")
async def overview(environment: str = "dev"):
    current = get_environment(environment)
    services = current["services"]

    async def check(name: str, key: str):
        base_url = services.get(key)
        if not base_url:
            return {"name": name, "status": "unconfigured", "latency_ms": None}
        started = datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{base_url.rstrip('/')}/healthz")
                response.raise_for_status()
                body = response.json()
            latency = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            return {"name": name, "status": "healthy", "latency_ms": round(latency), "detail": body}
        except (httpx.HTTPError, ValueError):
            return {"name": name, "status": "offline", "latency_ms": None}

    results = await asyncio.gather(
        *(check(name, key) for name, key in SERVICE_KEYS.items())
    )
    return {
        "environment": environment,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": results,
        "healthy": sum(item["status"] == "healthy" for item in results),
        "total": len(results),
        "grafana_url": current.get("grafana", ""),
    }


@app.get("/api/incidents")
async def incidents(environment: str = "dev"):
    return await forward(environment, "aiops", "/incidents")


@app.post("/api/simulate-incident")
async def simulate_incident(environment: str = "dev"):
    return await forward(environment, "aiops", "/simulate", payload={})


@app.post("/api/ask")
async def ask(body: dict, environment: str = "dev"):
    return await forward(environment, "docs", "/ask", payload=body)


@app.post("/api/predict")
async def predict(body: dict, environment: str = "dev"):
    return await forward(environment, "model", "/predict", payload=body)


@app.post("/api/chat")
async def chat(body: dict, environment: str = "dev"):
    body["caller"] = "portal"
    return await forward(environment, "gateway", "/v1/chat", payload=body)


class CostRequest(BaseModel):
    instance_type: Literal["t3.small", "t3.medium", "t3.large"] = "t3.medium"
    node_count: int = Field(default=2, ge=0, le=100)
    hours_per_month: int = Field(default=730, ge=1, le=744)
    ebs_gb: int = Field(default=100, ge=0, le=100000)
    s3_gb: int = Field(default=50, ge=0, le=1000000)
    nat_gateways: int = Field(default=1, ge=0, le=20)
    nat_data_gb: int = Field(default=100, ge=0, le=1000000)
    load_balancers: int = Field(default=1, ge=0, le=100)
    image_storage_gb: float = Field(default=5, ge=0, le=100000)
    replicas: int = Field(default=2, ge=1, le=100)
    container_cpu: float = Field(default=0.5, ge=0.1, le=128)
    container_memory_gb: float = Field(default=1, ge=0.1, le=1024)
    include_eks: bool = True


INSTANCE_RATES = {"t3.small": 0.0208, "t3.medium": 0.0416, "t3.large": 0.0832}


def estimate_cost(values: CostRequest) -> dict:
    hours = values.hours_per_month
    lines = [
        {"service": f"EC2 {values.instance_type} workers", "monthly_usd": values.node_count * hours * INSTANCE_RATES[values.instance_type]},
        {"service": "EBS gp3 storage", "monthly_usd": values.ebs_gb * 0.08},
        {"service": "S3 Standard storage", "monthly_usd": values.s3_gb * 0.023},
        {"service": "NAT Gateway hours", "monthly_usd": values.nat_gateways * hours * 0.045},
        {"service": "NAT Gateway data", "monthly_usd": values.nat_data_gb * 0.045},
        {"service": "Application Load Balancers", "monthly_usd": values.load_balancers * hours * 0.0225},
        {"service": "ECR image storage", "monthly_usd": values.image_storage_gb * 0.10},
        {"service": "EKS control plane", "monthly_usd": hours * 0.10 if values.include_eks else 0},
    ]
    total = sum(line["monthly_usd"] for line in lines)
    recommendations = []
    if values.node_count > 2:
        recommendations.append("Compare measured p95 CPU and memory before reducing worker count; do not right-size from this estimate alone.")
    if values.nat_gateways > 1:
        recommendations.append("Review NAT Gateway count and traffic paths; cross-AZ resilience requirements may justify the cost.")
    if values.image_storage_gb > 20:
        recommendations.append("Apply an ECR lifecycle policy and remove untagged build layers after validating rollback retention.")
    if values.replicas > 1:
        recommendations.append("Set requests and limits from observed container usage, then compare the smallest safe replica footprint.")
    if not recommendations:
        recommendations.append("Collect real utilization and billing data before changing capacity; this planner uses configurable baseline rates.")
    return {
        "currency": "USD",
        "monthly_usd": round(total, 2),
        "annual_usd": round(total * 12, 2),
        "line_items": [{**line, "monthly_usd": round(line["monthly_usd"], 2)} for line in lines],
        "container_plan": {
            "replicas": values.replicas,
            "cpu_cores": values.container_cpu,
            "memory_gb": values.container_memory_gb,
            "allocation_equivalent_usd": round(values.replicas * hours * (values.container_cpu * INSTANCE_RATES[values.instance_type] / 2 + values.container_memory_gb * INSTANCE_RATES[values.instance_type] / (2 if values.instance_type == "t3.small" else 4 if values.instance_type == "t3.medium" else 8)), 2),
            "included_in_worker_estimate": True,
        },
        "recommendations": recommendations,
        "disclaimer": "Planning estimate only. Rates are illustrative us-east-1 baselines, not live AWS pricing or account billing. Taxes, discounts, transfer, support, and service-specific usage are excluded.",
    }


@app.post("/api/cost-estimate")
def cost_estimate(body: CostRequest):
    return estimate_cost(body)


@app.get("/api/containers")
async def containers(request: Request, environment: str = "dev"):
    current = get_environment(environment)
    require_ops_access(request)
    if current.get("namespaces"):
        return await kube_containers(current)
    if not DOCKER_API_URL or environment != "dev":
        return {"configured": False, "containers": [], "message": "Read-only Docker inventory is enabled for the local dev environment only."}
    filters = json.dumps({"label": [f"com.docker.compose.project={COMPOSE_PROJECT}"]})
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{DOCKER_API_URL}/containers/json", params={"all": "1", "filters": filters})
            response.raise_for_status()
            items = response.json()
    except (httpx.HTTPError, ValueError):
        return {"configured": False, "containers": [], "message": "Docker inventory is unavailable. Start the optional read-only Docker proxy."}
    result = []
    for item in items:
        labels = item.get("Labels") or {}
        result.append({
            "id": item.get("Id", "")[:12],
            "name": (item.get("Names") or ["container"])[0].lstrip("/"),
            "service": labels.get("com.docker.compose.service", "container"),
            "state": item.get("State", "unknown"),
            "status": item.get("Status", ""),
        })
    return {"configured": True, "containers": result, "message": "Read-only Docker Engine inventory."}


def decode_docker_logs(content: bytes) -> str:
    chunks = []
    offset = 0
    while offset + 8 <= len(content):
        size = struct.unpack(">I", content[offset + 4:offset + 8])[0]
        if size < 0 or offset + 8 + size > len(content):
            break
        chunks.append(content[offset + 8:offset + 8 + size])
        offset += 8 + size
    return b"".join(chunks).decode("utf-8", errors="replace") if chunks else content.decode("utf-8", errors="replace")


@app.get("/api/logs/{service}")
async def container_logs(
    service: str,
    request: Request,
    environment: str = "dev",
    tail: int = Query(default=100, ge=1, le=500),
):
    current = get_environment(environment)
    require_ops_access(request)
    if service not in {*SERVICE_NAMES, "portal", "prometheus", "grafana"}:
        raise HTTPException(404, "Unknown service")
    namespace = current.get("namespaces", {}).get(service)
    if namespace:
        selector = current.get("workload_labels", {}).get(service, f"app={service}")
        pod_response = await kube_get(namespace, "pods", {"labelSelector": selector})
        pods = pod_response.json().get("items", [])
        pod = next((item for item in pods if item.get("status", {}).get("phase") == "Running"), None)
        if not pod:
            raise HTTPException(404, "No running pod was found for this service")
        pod_name = pod.get("metadata", {}).get("name", "")
        try:
            response = await kube_get(
                namespace,
                f"pods/{pod_name}/log",
                {"tailLines": tail, "timestamps": "true", "container": service},
            )
        except HTTPException as exc:
            if exc.status_code == 400:
                response = await kube_get(namespace, f"pods/{pod_name}/log", {"tailLines": tail, "timestamps": "true"})
            else:
                raise
        return {"service": service, "container": pod_name, "lines": response.text}
    if not DOCKER_API_URL or environment != "dev":
        raise HTTPException(503, "Container logs are not configured for this environment")
    filters = json.dumps({"label": [f"com.docker.compose.project={COMPOSE_PROJECT}"]})
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{DOCKER_API_URL}/containers/json", params={"all": "1", "filters": filters})
            response.raise_for_status()
            match = next((item for item in response.json() if (item.get("Labels") or {}).get("com.docker.compose.service") == service), None)
            if not match:
                raise HTTPException(404, "No matching project container was found")
            logs = await client.get(
                f"{DOCKER_API_URL}/containers/{match['Id']}/logs",
                params={"stdout": "1", "stderr": "1", "tail": str(tail), "timestamps": "1"},
            )
            logs.raise_for_status()
            return {"service": service, "container": (match.get("Names") or [service])[0].lstrip("/"), "lines": decode_docker_logs(logs.content)}
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "Container logs could not be read")


@app.post("/api/reports")
async def generate_report(body: dict):
    environment = body.get("environment", "dev")
    current = get_environment(environment)
    snapshot = await overview(environment)
    cost = estimate_cost(CostRequest(**body.get("cost_inputs", {})))
    try:
        incident_data = await forward(environment, "aiops", "/incidents")
    except HTTPException:
        incident_data = {"incidents": [], "remediation_enabled": False}
    return {
        "title": "AI IDP Operations Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "service_health": snapshot["services"],
        "container_inventory": "read-only Docker inventory is optional and is not included in this report",
        "incident_summary": {
            "count": len(incident_data.get("incidents", [])),
            "remediation_enabled": incident_data.get("remediation_enabled", False),
        },
        "cost_estimate": cost,
        "environment_configured": bool(current.get("services")),
    }


if WEB_ROOT.joinpath("index.html").exists():
    app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if not WEB_ROOT.joinpath("index.html").exists():
        raise HTTPException(503, "Web assets are not built. Run npm run build in services/portal/web.")
    return FileResponse(WEB_ROOT / "index.html")
