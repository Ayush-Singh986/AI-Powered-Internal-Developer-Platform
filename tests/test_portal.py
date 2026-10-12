from fastapi.testclient import TestClient

from services.portal import app as portal


def test_portal_health_and_environment_profiles():
    client = TestClient(portal.app)

    assert client.get("/healthz").json() == {"status": "ok", "service": "portal"}
    environments = client.get("/api/config").json()["environments"]
    assert next(item for item in environments if item["name"] == "dev")["configured"] is True
    assert next(item for item in environments if item["name"] == "staging")["configured"] is False
    assert client.get("/api/overview?environment=staging").status_code == 404


def test_cost_estimate_includes_service_and_container_assumptions():
    client = TestClient(portal.app)
    baseline = client.post("/api/cost-estimate", json={}).json()
    no_eks = client.post("/api/cost-estimate", json={"include_eks": False}).json()
    larger_container = client.post(
        "/api/cost-estimate",
        json={"replicas": 4, "container_cpu": 1.0, "container_memory_gb": 2.0},
    ).json()

    assert baseline["monthly_usd"] > no_eks["monthly_usd"]
    assert baseline["container_plan"]["included_in_worker_estimate"] is True
    assert larger_container["container_plan"]["allocation_equivalent_usd"] > baseline["container_plan"]["allocation_equivalent_usd"]


def test_container_inventory_requires_ops_token(monkeypatch):
    monkeypatch.setattr(portal, "OPS_API_TOKEN", "test-ops-token")
    monkeypatch.setattr(portal, "DOCKER_API_URL", "")
    client = TestClient(portal.app)

    assert client.get("/api/containers").status_code == 401
    response = client.get("/api/containers", headers={"Authorization": "Bearer test-ops-token"})
    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_cost_estimate_rejects_invalid_inputs():
    client = TestClient(portal.app)

    assert client.post("/api/cost-estimate", json={"node_count": -1}).status_code == 422