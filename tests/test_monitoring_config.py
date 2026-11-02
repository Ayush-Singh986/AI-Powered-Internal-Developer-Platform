import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def load_resources(path: str) -> list[dict]:
    return list(yaml.safe_load_all((ROOT / path).read_text(encoding="utf-8")))


class MonitoringConfigTests(unittest.TestCase):
    def test_prometheus_scrape_jobs_supply_service_down_labels(self) -> None:
        config = load_config("monitoring/prometheus.yml")
        jobs = {
            job["job_name"]: {
                relabel["target_label"]: relabel["replacement"]
                for relabel in job.get("relabel_configs", [])
            }
            for job in config["scrape_configs"]
        }

        for service in ("rag", "model-serving", "llm-gateway", "aiops-agent"):
            with self.subTest(service=service):
                self.assertEqual(jobs[service]["namespace"], service)
                self.assertEqual(jobs[service]["deployment"], service)

    def test_alert_rules_cover_metrics_available_to_the_stack(self) -> None:
        rules = load_config("monitoring/alerts.yml")["groups"][0]["rules"]
        by_name = {rule["alert"]: rule for rule in rules}

        self.assertIn(
            'up{job=~"rag|model-serving|llm-gateway|aiops-agent"} == 0',
            by_name["ServiceDown"]["expr"],
        )
        self.assertEqual(by_name["AIOpsAgentDown"]["expr"], 'up{job="aiops-agent"} == 0')
        self.assertEqual(
            by_name["AIOpsAgentDown"]["labels"]["external_notification"],
            "disabled",
        )
        self.assertIn(
            'increase(llm_gateway_requests_total{outcome="error"}[5m]) > 2',
            by_name["GatewayProviderErrors"]["expr"],
        )
        self.assertEqual(
            by_name["GatewayProviderErrors"]["labels"]["external_notification"],
            "disabled",
        )
        self.assertIn("llm_gateway_requests_total", by_name["GatewayErrorRate"]["expr"])
        self.assertIn(
            "llm_request_duration_seconds_bucket",
            by_name["GatewayHighP95Latency"]["expr"],
        )
        self.assertIn(
            "kube_pod_container_status_restarts_total",
            by_name["ContainerRestarting"]["expr"],
        )
        self.assertIn(
            "kube_pod_container_status_last_terminated_reason",
            by_name["ContainerOOMKilled"]["expr"],
        )
        self.assertEqual(by_name["Watchdog"]["expr"], "vector(1)")
        self.assertEqual(by_name["Watchdog"]["labels"]["external_heartbeat"], "disabled")

    def test_alertmanager_resolves_locally_and_gates_external_delivery(self) -> None:
        config = load_config("monitoring/alertmanager.yml")
        receivers = {receiver["name"]: receiver for receiver in config["receivers"]}
        routes = config["route"]["routes"]

        self.assertTrue(receivers["aiops-agent"]["webhook_configs"][0]["send_resolved"])
        authorization = receivers["aiops-agent"]["webhook_configs"][0]["http_config"]["authorization"]
        self.assertEqual(authorization["type"], "Bearer")
        self.assertEqual(
            authorization["credentials_file"],
            "/run/secrets/alertmanager-webhook-token",
        )
        external = receivers["outside-webhook"]["webhook_configs"][0]
        self.assertEqual(external["url_file"], "/etc/alertmanager/secrets/external-webhook-url")
        self.assertTrue(external["send_resolved"])
        self.assertTrue(any(route.get("matchers") == ['external_heartbeat="enabled"'] for route in routes))
        self.assertTrue(any(route.get("matchers") == ['external_notification="enabled"'] for route in routes))
        self.assertEqual(routes[-1]["receiver"], "aiops-agent")

    def test_kubernetes_alerts_match_worker_coverage_and_labels(self) -> None:
        local_rules = load_config("monitoring/alerts.yml")["groups"][0]["rules"]
        resources = load_resources("monitoring/k8s/k8s-resources.yaml")
        prometheus_rule = next(
            resource for resource in resources if resource["kind"] == "PrometheusRule"
        )
        kubernetes_rules = prometheus_rule["spec"]["groups"][0]["rules"]
        by_name = {rule["alert"]: rule for rule in kubernetes_rules}

        self.assertEqual(
            set(by_name),
            {rule["alert"] for rule in local_rules},
        )
        self.assertIn("deployment", by_name["ServiceDown"]["expr"])
        self.assertIn("namespace", by_name["ServiceDown"]["labels"])
        self.assertIn("deployment", by_name["ServiceDown"]["labels"])
        self.assertEqual(
            by_name["AIOpsAgentDown"]["labels"]["external_notification"],
            "enabled",
        )
        self.assertEqual(
            by_name["GatewayProviderErrors"]["labels"]["external_notification"],
            "enabled",
        )
        self.assertEqual(
            by_name["Watchdog"]["labels"]["external_heartbeat"],
            "enabled",
        )

    def test_kubernetes_alertmanager_uses_dedicated_token_and_resolves(self) -> None:
        resources = load_resources("monitoring/k8s/k8s-resources.yaml")
        config = next(
            resource for resource in resources if resource["kind"] == "AlertmanagerConfig"
        )
        receiver = next(
            receiver
            for receiver in config["spec"]["receivers"]
            if receiver["name"] == "aiops-agent"
        )
        webhook = receiver["webhookConfigs"][0]
        authorization = webhook["httpConfig"]["authorization"]

        self.assertTrue(webhook["sendResolved"])
        self.assertEqual(authorization["type"], "Bearer")
        self.assertEqual(authorization["credentials"]["name"], "alertmanager-webhook")
        self.assertEqual(
            authorization["credentials"]["key"],
            "ALERTMANAGER_WEBHOOK_TOKEN",
        )
        self.assertIn(
            "watchdog-ignored",
            {item["name"] for item in config["spec"]["receivers"]},
        )
        self.assertEqual(
            load_config("monitoring/kube-prometheus-values.yaml")["alertmanager"][
                "alertmanagerSpec"
            ]["alertmanagerConfigMatcherStrategy"]["type"],
            "None",
        )

    def test_kubernetes_external_receiver_is_explicitly_optional(self) -> None:
        optional_path = "monitoring/k8s/alertmanager-external.yaml"
        optional = load_config(optional_path)
        kustomization = load_config("monitoring/k8s/kustomization.yaml")
        routes = optional["spec"]["route"]["routes"]
        receiver = next(
            receiver
            for receiver in optional["spec"]["receivers"]
            if receiver["name"] == "outside-webhook"
        )

        self.assertNotIn("alertmanager-external.yaml", kustomization["resources"])
        self.assertEqual(
            receiver["webhookConfigs"][0]["urlSecret"],
            {"name": "external-webhook-url", "key": "url"},
        )
        self.assertEqual(
            {matcher["name"] for route in routes for matcher in route["matchers"]},
            {"external_notification", "external_heartbeat"},
        )
        heartbeat_route = next(
            route
            for route in routes
            if route["matchers"][0]["name"] == "external_heartbeat"
        )
        self.assertEqual(heartbeat_route["repeatInterval"], "1m")


if __name__ == "__main__":
    unittest.main()
