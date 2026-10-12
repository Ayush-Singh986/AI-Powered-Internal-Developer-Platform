import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from conftest import load

os.environ["MODEL_PATH"] = os.path.join(tempfile.gettempdir(), "test_deploy_risk.joblib")


def test_gateway_caches_and_counts_cost():
    c = TestClient(load("llm-gateway").app)
    body = {"prompt": "hello world", "caller": "test"}
    first = c.post("/v1/chat", json=body).json()
    second = c.post("/v1/chat", json=body).json()
    assert first["cached"] is False and first["cost_usd"] > 0
    assert second["cached"] is True and second["cost_usd"] == 0
    assert "llm_cost_usd_total" in c.get("/metrics").text


def test_gateway_rejects_empty_prompt():
    c = TestClient(load("llm-gateway").app)
    assert c.post("/v1/chat", json={"prompt": ""}).status_code == 422


def test_model_risk_goes_up_with_risky_inputs():
    c = TestClient(load("model-serving").app)
    safe = c.post("/predict", json={"files_changed": 2, "lines_changed": 30, "test_coverage": 95,
                                     "hour_of_day": 10, "recent_failures": 0}).json()
    risky = c.post("/predict", json={"files_changed": 70, "lines_changed": 2800, "test_coverage": 25,
                                      "hour_of_day": 19, "recent_failures": 5}).json()
    assert risky["risk_score"] > safe["risk_score"]
    assert c.get("/model/info").json()["data"] == "synthetic"


def test_docs_assistant_falls_back_when_gateway_down(monkeypatch):
    m = load("docs-assistant")
    monkeypatch.setattr(m, "GATEWAY_URL", "http://127.0.0.1:1")
    c = TestClient(m.app)
    d = c.post("/ask", json={"question": "How do I roll back a deploy?"}).json()
    assert d["llm_used"] is False
    assert d["sources"][0]["file"] == "deploy-runbook.md"


def test_aiops_dry_run_and_cooldown():
    m = load("aiops-agent")
    c = TestClient(m.app)
    a = c.post("/simulate", json={"service": "docs-assistant"}).json()
    b = c.post("/simulate", json={"service": "docs-assistant"}).json()
    assert a["action"] == "dry_run"
    assert b["action"] == "skipped_cooldown"
    assert c.post("/simulate", json={"rule": "nope"}).status_code == 400
    assert c.post("/simulate", json={"service": "portal"}).json()["action"] == "ignored_unmanaged"
