import os

import requests
import streamlit as st

from incident_helpers import diagnosis_summary, incident_summary

st.set_page_config(page_title="AIOps Platform", page_icon="📡", layout="wide")
st.title("AIOps Platform")
st.caption("Live service health and Alertmanager incidents. No sample incidents are generated.")

SERVICES = {
    "Runbook retrieval": os.getenv("RAG_URL", "http://rag:8000"),
    "Model adapter": os.getenv("GATEWAY_URL", "http://llm-gateway:8000"),
    "LLM gateway": os.getenv("GATEWAY_URL", "http://llm-gateway:8000"),
    "AIOps agent": os.getenv("AGENT_URL", "http://aiops-agent:8000"),
}
HEALTH_PATHS = {"Model adapter": "/dependencies/model-serving"}
AGENT_SERVICE_TOKEN = os.getenv("AGENT_SERVICE_TOKEN", "")
PORTAL_GATEWAY_API_KEY = os.getenv("PORTAL_GATEWAY_API_KEY", "")
AIOPS_ACTION_TOKEN = os.getenv("AIOPS_ACTION_TOKEN", "")


def auth_headers(token: str) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


@st.fragment(run_every="10s")
def service_health():
    left, right = st.columns(2)
    for index, (name, url) in enumerate(SERVICES.items()):
        with (left if index % 2 == 0 else right):
            try:
                path = HEALTH_PATHS.get(name, "/health")
                response = requests.get(
                    f"{url}{path}",
                    headers=auth_headers(PORTAL_GATEWAY_API_KEY) if name == "Model adapter" else {},
                    timeout=3,
                )
                response.raise_for_status()
                if response.json().get("status") == "ok":
                    st.success(f"{name}: healthy")
                else:
                    st.error(f"{name}: unavailable")
            except requests.RequestException:
                st.error(f"{name}: unavailable")


service_health()

st.link_button("Open Grafana", os.getenv("GRAFANA_URL", "http://localhost:3000"))
st.subheader("Incident feed")


@st.fragment(run_every="10s")
def incident_feed():
    if not AGENT_SERVICE_TOKEN:
        st.error("Incident feed unavailable: service authentication is not configured.")
        return

    try:
        response = requests.get(
            f"{SERVICES['AIOps agent']}/incidents",
            headers=auth_headers(AGENT_SERVICE_TOKEN),
            timeout=5,
        )
        response.raise_for_status()
        incidents = response.json()
        if incidents:
            st.dataframe(
                [incident_summary(incident) for incident in incidents],
                use_container_width=True,
                hide_index=True,
            )
            for index, incident in enumerate(incidents):
                incident_id = str(incident.get("id", index))
                feedback_columns = st.columns(2)
                if feedback_columns[0].button(
                    "Diagnosis helpful",
                    key=f"feedback-up-{incident_id}",
                    disabled=not AGENT_SERVICE_TOKEN,
                ):
                    feedback_response = requests.post(
                        f"{SERVICES['AIOps agent']}/incidents/{incident_id}/feedback",
                        json={"rating": 1},
                        headers=auth_headers(AGENT_SERVICE_TOKEN),
                        timeout=5,
                    )
                    feedback_response.raise_for_status()
                    st.success("Feedback saved.")
                    st.rerun()
                if feedback_columns[1].button(
                    "Diagnosis not helpful",
                    key=f"feedback-down-{incident_id}",
                    disabled=not AGENT_SERVICE_TOKEN,
                ):
                    feedback_response = requests.post(
                        f"{SERVICES['AIOps agent']}/incidents/{incident_id}/feedback",
                        json={"rating": -1},
                        headers=auth_headers(AGENT_SERVICE_TOKEN),
                        timeout=5,
                    )
                    feedback_response.raise_for_status()
                    st.success("Feedback saved.")
                    st.rerun()
                raw_diagnosis = incident.get("diagnosis_json")
                diagnosis = diagnosis_summary(raw_diagnosis)
                if diagnosis:
                    st.markdown(f"**Model suggestion for {incident_id}**")
                    st.json(diagnosis)
                    suggestion = diagnosis.get("action")
                    decision = diagnosis.get("decision") or {}
                    if (
                        suggestion in {"restart_deployment", "scale_deployment"}
                        and decision.get("status") == "pending_human_review"
                    ):
                        replicas = (
                            st.number_input(
                                f"Replicas for incident {incident_id}",
                                min_value=1,
                                max_value=5,
                                value=2,
                                key=f"replicas-{incident_id}",
                            )
                            if suggestion == "scale_deployment"
                            else None
                        )
                        if st.button(
                            f"Approve {suggestion.replace('_', ' ')} for {incident_id}",
                            key=f"approve-{incident_id}",
                            disabled=not AIOPS_ACTION_TOKEN,
                        ):
                            payload = {"action": suggestion}
                            if replicas is not None:
                                payload["replicas"] = int(replicas)
                            result = requests.post(
                                f"{SERVICES['AIOps agent']}/incidents/{incident_id}/actions",
                                json=payload,
                                headers=auth_headers(AIOPS_ACTION_TOKEN),
                                timeout=10,
                            )
                            result.raise_for_status()
                            st.success("Human approval recorded and action submitted.")
                            st.rerun()
                if st.checkbox(
                    f"Reveal evidence and logs for incident {incident_id}",
                    key=f"reveal-evidence-{incident_id}",
                ):
                    evidence_response = requests.get(
                        f"{SERVICES['AIOps agent']}/incidents/{incident_id}/evidence",
                        headers=auth_headers(AGENT_SERVICE_TOKEN),
                        timeout=5,
                    )
                    evidence_response.raise_for_status()
                    st.json(
                        {
                            "evidence": evidence_response.json().get("evidence", {}),
                            "action_log": incident.get("action_log", []),
                        }
                    )
        else:
            st.info("No incidents have been received yet.")
    except requests.RequestException:
        st.error("Could not load incidents.")


incident_feed()

st.caption("Configure Alertmanager to POST firing alerts to the AIOps agent's /alerts endpoint.")
