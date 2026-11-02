import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class RagServiceTests(unittest.TestCase):
    def test_health_and_metrics(self):
        client = TestClient(app.app)
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        self.assertIn("rag_retrieval_requests_total", client.get("/metrics").text)

    def test_runbook_retrieval(self):
        with patch.object(app, "SERVICE_API_KEY", "service-token"):
            response = TestClient(app.app).post(
                "/retrieve",
                json={"query": "pod restarts termination logs", "limit": 1},
                headers={"Authorization": "Bearer service-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], "pod-restarts.md")

    def test_alert_name_selects_matching_runbook(self):
        with patch.object(app, "SERVICE_API_KEY", "rag-token"):
            response = TestClient(app.app).post(
                "/retrieve",
                json={
                    "query": "service unavailable",
                    "alert_name": "ServiceDown",
                    "limit": 1,
                },
                headers={"Authorization": "Bearer rag-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], "service-down.md")

    def test_retrieval_requires_service_authentication(self):
        with patch.object(app, "SERVICE_API_KEY", "service-token"):
            response = TestClient(app.app).post(
                "/retrieve", json={"query": "pod restarts"}
            )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
