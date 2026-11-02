import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class ModelServiceTests(unittest.TestCase):
    def test_health_and_metrics(self):
        client = TestClient(app.app)
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertIn("model_requests_total", client.get("/metrics").text)

    def test_fails_explicitly_without_provider_configuration(self):
        with patch.object(app, "BASE_URL", ""), patch.object(app, "SERVICE_API_KEY", "test-token"):
            response = TestClient(app.app).post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "diagnose"}]},
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("LLM_BASE_URL", response.json()["detail"])

    def test_requires_service_authentication(self):
        with patch.object(app, "SERVICE_API_KEY", ""):
            response = TestClient(app.app).post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "diagnose"}]},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("MODEL_SERVICE_API_KEY", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
