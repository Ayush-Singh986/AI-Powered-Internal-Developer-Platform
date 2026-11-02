import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

import app


WEBHOOK_HEADERS = {"Authorization": "Bearer webhook-token"}
SERVICE_HEADERS = {"Authorization": "Bearer agent-token"}
ACTION_HEADERS = {"Authorization": "Bearer action-token"}


class AgentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(app, "DB_PATH", Path(directory.name) / "incidents.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def alert(self, status="firing", fingerprint="test-fingerprint"):
        return {
            "status": status,
            "fingerprint": fingerprint,
            "startsAt": "2025-01-01T00:00:00Z",
            "endsAt": "2025-01-01T00:01:00Z" if status == "resolved" else "0001-01-01T00:00:00Z",
            "labels": {
                "alertname": "ServiceDown",
                "namespace": "rag",
                "deployment": "rag",
            },
            "annotations": {"summary": "Service is down", "description": "Scrape failed"},
        }

    def post_alerts(self, client, alerts):
        return client.post(
            "/alerts",
            json={"alerts": alerts},
            headers=WEBHOOK_HEADERS,
        )

    def test_health_and_authenticated_incident_feed(self):
        with patch.object(app, "SERVICE_API_KEY", "agent-token"):
            client = TestClient(app.app)
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/incidents").status_code, 401)
            self.assertEqual(client.get("/incidents", headers=SERVICE_HEADERS).json(), [])
            self.assertIn("aiops_alerts_received_total", client.get("/metrics").text)

    def test_alert_webhook_uses_dedicated_token(self):
        with patch.object(app, "ALERTMANAGER_API_KEY", "webhook-token"):
            response = TestClient(app.app).post("/alerts", json={"alerts": []})
        self.assertEqual(response.status_code, 401)

    def test_invalid_alert_batch_is_rejected_after_authentication(self):
        with patch.object(app, "ALERTMANAGER_API_KEY", "webhook-token"):
            response = TestClient(app.app).post(
                "/alerts", json={"alerts": "not-a-list"}, headers=WEBHOOK_HEADERS
            )
        self.assertEqual(response.status_code, 422)

    def test_webhook_acknowledges_and_deduplicates_before_diagnosis(self):
        with patch.object(app, "ALERTMANAGER_API_KEY", "webhook-token"):
            with patch.object(app, "SERVICE_API_KEY", "agent-token"):
                with patch.object(app, "collect_evidence", return_value={"status": "disabled"}):
                    with patch.object(
                        app,
                        "diagnose_structured",
                        new=AsyncMock(
                            return_value={
                                "cause": "Scrape failure",
                                "action": "none",
                                "confidence": 0.8,
                                "rationale": "Check the target health.",
                                "decision": {"status": "pending_human_review"},
                            }
                        ),
                    ) as diagnose:
                        client = TestClient(app.app)
                        response = self.post_alerts(client, [self.alert()])
                        duplicates = [
                            self.post_alerts(client, [self.alert()]) for _ in range(9)
                        ]
                        self.assertEqual(response.status_code, 202)
                        self.assertEqual(response.json()["accepted"], 1)
                        self.assertTrue(
                            all(item.json()["alerts"][0]["duplicate"] for item in duplicates)
                        )
                        diagnose.assert_not_awaited()
                        self.assertTrue(asyncio.run(app.process_next_alert_job()))
                        incidents = client.get(
                            "/incidents", headers=SERVICE_HEADERS
                        ).json()
                        self.assertNotIn("evidence", incidents[0])
                        evidence = client.get(
                            f"/incidents/{incidents[0]['id']}/evidence",
                            headers=SERVICE_HEADERS,
                        )
        self.assertEqual(diagnose.await_count, 1)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["recommendation"], "Scrape failure")
        self.assertEqual(json.loads(incidents[0]["diagnosis_json"])["action"], "none")
        self.assertEqual(evidence.json()["evidence"], {"status": "disabled"})

    def test_resolved_alert_closes_incident_and_allows_reopen(self):
        with patch.object(app, "ALERTMANAGER_API_KEY", "webhook-token"):
            client = TestClient(app.app)
            firing = self.post_alerts(client, [self.alert()])
            first_id = firing.json()["alerts"][0]["id"]
            resolved = self.post_alerts(client, [self.alert(status="resolved")])
            self.assertTrue(resolved.json()["alerts"][0]["resolved"])
            reopened = self.post_alerts(client, [self.alert()])
        self.assertEqual(firing.status_code, 202)
        self.assertEqual(reopened.status_code, 202)
        self.assertNotEqual(reopened.json()["alerts"][0]["id"], first_id)
        with app.database() as connection:
            rows = connection.execute(
                "SELECT status, resolved_at FROM incidents ORDER BY created_at"
            ).fetchall()
        self.assertEqual(rows[0]["status"], "resolved")
        self.assertEqual(rows[0]["resolved_at"], "2025-01-01T00:01:00Z")
        self.assertEqual(rows[1]["status"], "firing")

    def test_retention_purges_old_resolved_incidents_and_jobs(self):
        old_date = "2024-01-01T00:00:00+00:00"
        with app.database() as connection:
            connection.execute(
                """INSERT INTO incidents
                (id, created_at, status, alert_name, summary, recommendation,
                 action_log, fingerprint, evidence, resolved_at)
                VALUES ('expired', ?, 'resolved', 'ServiceDown', 'old', 'done',
                 '[]', 'old-fingerprint', '{}', ?)""",
                (old_date, old_date),
            )
            connection.execute(
                """INSERT INTO alert_jobs
                (id, incident_id, alert_json, status, attempts, next_attempt_at,
                 created_at, updated_at)
                VALUES ('expired-job', 'expired', '{}', 'completed', 1, ?, ?, ?)""",
                (old_date, old_date, old_date),
            )
        self.assertEqual(app.purge_expired_incidents(), 1)
        with app.database() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT id FROM incidents WHERE id = 'expired'"
                ).fetchone()
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT id FROM alert_jobs WHERE id = 'expired-job'"
                ).fetchone()
            )

    def test_failed_diagnosis_is_retried_and_bounded(self):
        with patch.object(app, "ALERTMANAGER_API_KEY", "webhook-token"):
            with patch.object(app, "collect_evidence", return_value={"status": "disabled"}):
                with patch.object(app, "MAX_JOB_ATTEMPTS", 1):
                    with patch.object(
                        app, "diagnose_structured", new=AsyncMock(side_effect=RuntimeError("provider offline"))
                    ):
                        self.post_alerts(TestClient(app.app), [self.alert()])
                        self.assertTrue(asyncio.run(app.process_next_alert_job()))
        with app.database() as connection:
            job = connection.execute("SELECT status, attempts FROM alert_jobs").fetchone()
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["attempts"], 1)

    def test_action_requires_matching_pending_model_suggestion_and_audits_approval(self):
        incident_id = "approval-test"
        with app.database() as connection:
            connection.execute(
                """INSERT INTO incidents
                (id, created_at, status, alert_name, namespace, deployment, summary,
                 recommendation, action_log, fingerprint, evidence, diagnosis_json)
                VALUES (?, ?, 'firing', 'ServiceDown', 'rag', 'rag', 'summary',
                 'cause', '[]', 'approval-fingerprint', '{}', ?)""",
                (
                    incident_id,
                    "2025-01-01T00:00:00Z",
                    json.dumps(
                        {
                            "cause": "Scrape failure",
                            "action": "restart_deployment",
                            "confidence": 0.7,
                            "decision": {"status": "pending_human_review"},
                        }
                    ),
                ),
            )
        with patch.object(app, "ACTION_API_KEY", "action-token"):
            with patch.object(app, "execute_action", return_value="restarted") as execute:
                client = TestClient(app.app)
                approved = client.post(
                    f"/incidents/{incident_id}/actions",
                    json={"action": "restart_deployment"},
                    headers=ACTION_HEADERS,
                )
                repeated = client.post(
                    f"/incidents/{incident_id}/actions",
                    json={"action": "restart_deployment"},
                    headers=ACTION_HEADERS,
                )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(repeated.status_code, 409)
        execute.assert_called_once()
        with app.database() as connection:
            saved = connection.execute(
                "SELECT diagnosis_json, action_log FROM incidents WHERE id = ?",
                (incident_id,),
            ).fetchone()
        self.assertEqual(json.loads(saved["diagnosis_json"])["decision"]["status"], "approved")
        self.assertEqual(len(json.loads(saved["action_log"])), 1)

    def test_operator_feedback_is_stored_with_the_incident(self):
        with patch.object(app, "ALERTMANAGER_API_KEY", "webhook-token"):
            with patch.object(app, "SERVICE_API_KEY", "agent-token"):
                client = TestClient(app.app)
                self.post_alerts(client, [self.alert()])
                incident_id = client.get(
                    "/incidents", headers=SERVICE_HEADERS
                ).json()[0]["id"]
                response = client.post(
                    f"/incidents/{incident_id}/feedback",
                    json={"rating": -1},
                    headers=SERVICE_HEADERS,
                )
                incidents = client.get("/incidents", headers=SERVICE_HEADERS).json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(incidents[0]["feedback_rating"], -1)

    def test_action_rate_limit_writes_refusal_to_audit(self):
        with patch.object(app, "MAX_ACTIONS_PER_HOUR", 3):
            with patch.object(app, "execute_action", return_value="restarted"):
                for _ in range(3):
                    self.assertEqual(
                        app.run_action("rag", "rag", "restart_deployment", None),
                        "restarted",
                    )
                with self.assertRaises(app.HTTPException) as raised:
                    app.run_action("rag", "rag", "restart_deployment", None)
        self.assertEqual(raised.exception.status_code, 429)
        with app.database() as connection:
            records = connection.execute(
                "SELECT result FROM action_audit ORDER BY created_at"
            ).fetchall()
        self.assertEqual(len(records), 4)
        self.assertIn("refused", records[-1]["result"].lower())

    def test_evidence_collection_is_opt_in(self):
        with patch.object(app, "EVIDENCE_ENABLED_NAMESPACES", set()):
            evidence = app.collect_evidence("rag", "rag")
        self.assertEqual(evidence["status"], "disabled")

    def test_model_calls_are_limited_persistently(self):
        with patch.object(app, "MAX_LLM_CALLS_PER_HOUR", 1):
            self.assertTrue(app.reserve_llm_call())
            self.assertFalse(app.reserve_llm_call())

    def test_unknown_alert_cannot_receive_an_action_suggestion(self):
        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                return None

            async def post(self, url, **kwargs):
                response = MagicMock()
                response.raise_for_status.return_value = None
                if url.endswith("/retrieve"):
                    response.json.return_value = {"results": []}
                else:
                    response.json.return_value = {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "cause": "Unknown",
                                            "action": "restart_deployment",
                                            "confidence": 0.9,
                                            "rationale": "Unknown alert.",
                                        }
                                    )
                                }
                            }
                        ]
                    }
                return response

        with patch.object(app, "reserve_llm_call", return_value=True):
            with patch.object(app.httpx, "AsyncClient", FakeClient):
                result = asyncio.run(
                    app.diagnose_structured(
                        {
                            "labels": {"alertname": "UnknownAlert"},
                            "annotations": {"summary": "unknown"},
                        },
                        {},
                    )
                )
        self.assertEqual(result["action"], "none")
        self.assertEqual(result["decision"]["status"], "pending_human_review")

    def test_runbook_failure_does_not_skip_model_diagnosis(self):
        requests = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                return None

            async def post(self, url, **kwargs):
                requests.append(url)
                if url.endswith("/retrieve"):
                    raise httpx.ConnectError("RAG unavailable")
                response = MagicMock()
                response.raise_for_status.return_value = None
                response.json.return_value = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "cause": "Scrape unavailable",
                                        "action": "none",
                                        "confidence": 0.6,
                                        "rationale": "Check service health.",
                                    }
                                )
                            }
                        }
                    ]
                }
                return response

        with patch.object(app, "reserve_llm_call", return_value=True):
            with patch.object(app.httpx, "AsyncClient", FakeClient):
                diagnosis = asyncio.run(
                    app.diagnose_structured(
                        {
                            "labels": {"alertname": "ServiceDown"},
                            "annotations": {"summary": "service down"},
                        },
                        {},
                    )
                )
        self.assertEqual(len(requests), 2)
        self.assertIn("/retrieve", requests[0])
        self.assertIn("/v1/chat/completions", requests[1])
        self.assertEqual(diagnosis["cause"], "Scrape unavailable")

    def test_rejects_unlisted_action_and_namespace(self):
        with self.assertRaises(app.HTTPException) as raised:
            app.execute_action("other", "workload", "restart_deployment", None)
        self.assertEqual(raised.exception.status_code, 403)
        with self.assertRaises(app.HTTPException) as raised:
            app.execute_action("rag", "rag", "run_shell", None)
        self.assertEqual(raised.exception.status_code, 400)

    def test_scale_action_enforces_maximum_before_cluster_access(self):
        with self.assertRaises(app.HTTPException) as raised:
            app.execute_action("rag", "rag", "scale_deployment", app.MAX_REPLICAS + 1)
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
