import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import app


class FakeClient:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def post(self, *args, **kwargs):
        type(self).calls += 1
        response = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": "diagnosis"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 20},
        }
        return response


class GatewayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(app, "DATABASE_PATH", Path(directory.name) / "gateway.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(app, "GATEWAY_API_KEY", "gateway-token")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(app, "MODEL_SERVICE_API_KEY", "model-token")
        patcher.start()
        self.addCleanup(patcher.stop)
        app.RESPONSE_CACHE.clear()
        FakeClient.calls = 0

    def test_health_and_metrics(self):
        client = TestClient(app.app)
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertIn("llm_gateway_requests_total", client.get("/metrics").text)

    def test_request_validation_and_message_bounds(self):
        client = TestClient(app.app)
        self.assertEqual(client.post("/v1/chat/completions", json={"messages": []}).status_code, 422)
        invalid_role = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "tool", "content": "hello"}]},
        )
        self.assertEqual(invalid_role.status_code, 422)

    def test_empty_cost_rates_do_not_break_successful_requests(self):
        with patch.object(app, "INPUT_RATE", ""), patch.object(app, "OUTPUT_RATE", ""):
            response = self.post_chat(max_tokens=50)
        self.assertEqual(response.status_code, 200)

    def test_cost_uses_provider_token_usage_and_configured_rates(self):
        before = REGISTRY.get_sample_value("llm_cost_usd_total") or 0
        with patch.object(app, "INPUT_RATE", "0.01"), patch.object(app, "OUTPUT_RATE", "0.02"):
            response = self.post_chat(max_tokens=50, message="unique cost request")
        self.assertEqual(response.status_code, 200)
        after = REGISTRY.get_sample_value("llm_cost_usd_total")
        self.assertAlmostEqual(after - before, 0.00044)

    def test_requires_gateway_authentication(self):
        with patch.object(app, "GATEWAY_API_KEY", ""):
            response = self.post_chat(max_tokens=50)
        self.assertEqual(response.status_code, 503)
        self.assertIn("LLM_GATEWAY_API_KEY", response.json()["detail"])

    def test_missing_bearer_token_is_unauthorized_when_configured(self):
        with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
            response = TestClient(app.app).post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "test"}]},
            )
        self.assertEqual(response.status_code, 401)

    def test_daily_budget_is_reserved_before_model_call(self):
        with patch.object(app, "DAILY_TOKEN_LIMIT", 40):
            with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
                with patch.object(app, "MODEL_SERVICE_API_KEY", "model-token"):
                    first = self.post_chat(max_tokens=20, message="test")
                    second = self.post_chat(max_tokens=20, message="second request")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(FakeClient.calls, 1)

    def test_same_caller_reuses_bounded_in_memory_cache(self):
        with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
            with patch.object(app, "MODEL_SERVICE_API_KEY", "model-token"):
                first = self.post_chat(max_tokens=50, message="same prompt")
                second = self.post_chat(max_tokens=50, message="same prompt")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(FakeClient.calls, 1)

    def test_cache_is_isolated_by_bearer_token(self):
        with patch.object(app, "GATEWAY_CLIENT_KEYS", {
            "caller-one": "caller-one",
            "caller-two": "caller-two",
        }):
            with patch.object(app, "GATEWAY_API_KEY", ""):
                with patch.object(app, "MODEL_SERVICE_API_KEY", "model-token"):
                    self.post_chat(max_tokens=50, message="same prompt", token="caller-one")
                    self.post_chat(max_tokens=50, message="same prompt", token="caller-two")
        self.assertEqual(FakeClient.calls, 2)

    def test_input_size_is_limited(self):
        with patch.object(app, "MAX_INPUT_BYTES", 4):
            response = self.post_chat(max_tokens=20, message="12345")
        self.assertEqual(response.status_code, 413)

    def test_legacy_daily_usage_is_migrated(self):
        connection = sqlite3.connect(app.DATABASE_PATH)
        with connection:
            connection.execute(
                "CREATE TABLE daily_token_usage (usage_date TEXT PRIMARY KEY, tokens INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO daily_token_usage VALUES (?, ?)",
                ("2025-01-01", 123),
            )
        connection.close()
        self.assertEqual(app.daily_token_total(), 0)
        connection = sqlite3.connect(app.DATABASE_PATH)
        with connection:
            row = connection.execute(
                "SELECT caller_id, tokens FROM daily_token_usage"
            ).fetchone()
        connection.close()
        self.assertEqual(row, ("legacy", 123))

    def test_concurrent_budget_reservations_cannot_exceed_limit(self):
        with patch.object(app, "DAILY_TOKEN_LIMIT", 100):
            with patch.object(app, "CALLER_DAILY_TOKEN_LIMIT", 100):
                with ThreadPoolExecutor(max_workers=8) as executor:
                    reservations = list(
                        executor.map(
                            lambda _: app.reserve_request("same-caller", 30),
                            range(8),
                        )
                    )
        self.assertEqual(sum(item is not None for item in reservations), 3)
        self.assertLessEqual(app.daily_token_total(), 100)

    def test_connect_failure_retries_then_uses_fallback_provider(self):
        class FallbackClient(FakeClient):
            requested_urls = []

            async def post(self, url, **kwargs):
                self.requested_urls.append(url)
                if url.startswith("http://primary"):
                    raise httpx.ConnectError("primary unavailable")
                return await super().post(url, **kwargs)

        with patch.object(app, "GATEWAY_API_KEY", "gateway-token"):
            with patch.object(app, "MODEL_SERVICE_API_KEY", "model-token"):
                with patch.object(app, "MODEL_URL", "http://primary"):
                    with patch.object(app, "FALLBACK_MODEL_URL", "http://fallback"):
                        with patch.object(app.httpx, "AsyncClient", FallbackClient):
                            response = TestClient(app.app).post(
                                "/v1/chat/completions",
                                json={
                                    "messages": [
                                        {"role": "user", "content": "fallback test"}
                                    ],
                                    "max_tokens": 50,
                                },
                                headers={"Authorization": "Bearer gateway-token"},
                            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            FallbackClient.requested_urls,
            [
                "http://primary/v1/chat/completions",
                "http://primary/v1/chat/completions",
                "http://fallback/v1/chat/completions",
            ],
        )

    def post_chat(self, message="test", max_tokens=50, token="gateway-token"):
        with patch.object(app.httpx, "AsyncClient", FakeClient):
            return TestClient(app.app).post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": message}],
                    "max_tokens": max_tokens,
                },
                headers={"Authorization": f"Bearer {token}"},
            )


if __name__ == "__main__":
    unittest.main()
