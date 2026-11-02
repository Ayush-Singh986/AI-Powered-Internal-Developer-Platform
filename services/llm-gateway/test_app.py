import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import app


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def post(self, *args, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": "diagnosis"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        return response


class GatewayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(app, "DATABASE_PATH", Path(directory.name) / "gateway.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_health_and_metrics(self):
        client = TestClient(app.app)
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertIn("llm_gateway_requests_total", client.get("/metrics").text)

    def test_request_validation(self):
        response = TestClient(app.app).post("/v1/chat/completions", json={"messages": []})
        self.assertEqual(response.status_code, 422)

    def test_empty_cost_rates_do_not_break_successful_requests(self):
        with patch.object(app, "INPUT_RATE", ""), patch.object(app, "OUTPUT_RATE", ""):
            with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
                with patch.object(app, "MODEL_SERVICE_API_KEY", "model-token"):
                    response = self.post_chat()

        self.assertEqual(response.status_code, 200)

    def test_cost_uses_provider_token_usage_and_configured_rates(self):
        before = REGISTRY.get_sample_value("llm_cost_usd_total") or 0
        with patch.object(app, "INPUT_RATE", "0.01"), patch.object(app, "OUTPUT_RATE", "0.02"):
            with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
                with patch.object(app, "MODEL_SERVICE_API_KEY", "model-token"):
                    response = self.post_chat()
        self.assertEqual(response.status_code, 200)
        after = REGISTRY.get_sample_value("llm_cost_usd_total")
        self.assertAlmostEqual(after - before, 0.002)

    def test_requires_gateway_authentication(self):
        with patch.object(app, "GATEWAY_API_KEY", ""):
            response = self.post_chat()
        self.assertEqual(response.status_code, 503)
        self.assertIn("LLM_GATEWAY_API_KEY", response.json()["detail"])

    def test_missing_bearer_token_is_unauthorized_when_configured(self):
        with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
            response = TestClient(app.app).post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "test"}]},
            )
        self.assertEqual(response.status_code, 401)

    def test_daily_token_limit_rejects_later_requests(self):
        with patch.object(app, "DAILY_TOKEN_LIMIT", 100):
            with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
                with patch.object(app, "MODEL_SERVICE_API_KEY", "model-token"):
                    first = self.post_chat()
                    second = self.post_chat()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def post_chat(self):
        with patch.object(app.httpx, "AsyncClient", FakeClient):
            return TestClient(app.app).post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={"Authorization": "Bearer gateway-token"},
            )


if __name__ == "__main__":
    unittest.main()
