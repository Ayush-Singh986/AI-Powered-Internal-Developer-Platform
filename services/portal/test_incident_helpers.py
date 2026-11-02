import json
import unittest

from incident_helpers import diagnosis_summary, incident_summary


class IncidentHelperTests(unittest.TestCase):
    def test_incident_summary_does_not_expose_evidence(self):
        summary = incident_summary(
            {
                "id": "incident-1",
                "status": "firing",
                "alert_name": "ServiceDown",
                "created_at": "2025-01-01T00:00:00Z",
                "summary": "Service is down",
                "evidence": {"logs": ["private log line"]},
                "action_log": [{"result": "action details"}],
            }
        )
        self.assertEqual(
            set(summary),
            {"id", "status", "alert", "created", "summary"},
        )
        self.assertNotIn("private log line", json.dumps(summary))

    def test_diagnosis_summary_only_exposes_suggestion_fields(self):
        summary = diagnosis_summary(
            json.dumps(
                {
                    "cause": "Unhealthy target",
                    "action": "none",
                    "confidence": 0.8,
                    "rationale": "Check the target.",
                    "decision": {"status": "pending_human_review"},
                    "evidence": {"logs": ["private log line"]},
                }
            )
        )
        self.assertEqual(
            set(summary or {}),
            {"cause", "action", "confidence", "rationale", "decision"},
        )

    def test_invalid_diagnosis_is_reported(self):
        self.assertEqual(
            diagnosis_summary("{"),
            {"error": "Saved diagnosis is not valid JSON."},
        )


if __name__ == "__main__":
    unittest.main()
