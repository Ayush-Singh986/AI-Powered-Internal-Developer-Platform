import json
from typing import Any


def incident_summary(incident: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(incident.get("id", "")),
        "status": str(incident.get("status", "")),
        "alert": str(incident.get("alert_name", "")),
        "created": str(incident.get("created_at", "")),
        "summary": str(incident.get("summary", "")),
    }


def diagnosis_summary(raw_diagnosis: str | None) -> dict[str, Any] | None:
    if not raw_diagnosis:
        return None
    try:
        diagnosis = json.loads(raw_diagnosis)
    except json.JSONDecodeError:
        return {"error": "Saved diagnosis is not valid JSON."}
    if not isinstance(diagnosis, dict):
        return {"error": "Saved diagnosis has an invalid shape."}
    return {
        key: diagnosis.get(key)
        for key in ("cause", "action", "confidence", "rationale", "decision")
    }
