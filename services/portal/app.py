import os

import requests
import streamlit as st

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
SERVICE_AUTH_TOKEN = os.getenv("SERVICE_AUTH_TOKEN", "")
@st.fragment(run_every="10s")
def service_health():
    left, right = st.columns(2)
    for index, (name, url) in enumerate(SERVICES.items()):
        with (left if index % 2 == 0 else right):
            try:
                path = HEALTH_PATHS.get(name, "/health")
                headers = (
                    {"Authorization": f"Bearer {SERVICE_AUTH_TOKEN}"}
                    if name == "Model adapter"
                    else {}
                )
                response = requests.get(f"{url}{path}", headers=headers, timeout=3)
                response.raise_for_status()
                if response.json().get("status") == "ok":
                    st.success(f"{name}: healthy")
                else:
                    st.error(f"{name}: unavailable")
            except requests.RequestException as exc:
                st.error(f"{name}: unavailable ({exc})")


service_health()

st.link_button("Open Grafana", os.getenv("GRAFANA_URL", "http://localhost:3000"))
st.subheader("Incident feed")


@st.fragment(run_every="10s")
def incident_feed():
    try:
        response = requests.get(
            f"{SERVICES['AIOps agent']}/incidents",
            headers={"Authorization": f"Bearer {SERVICE_AUTH_TOKEN}"},
            timeout=5,
        )
        response.raise_for_status()
        incidents = response.json()
        if incidents:
            st.dataframe(incidents, use_container_width=True, hide_index=True)
        else:
            st.info("No incidents have been received yet.")
    except requests.RequestException as exc:
        st.error(f"Could not load incidents: {exc}")


incident_feed()

st.caption("Configure Alertmanager to POST firing alerts to the AIOps agent's /alerts endpoint.")
