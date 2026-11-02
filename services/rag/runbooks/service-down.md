# ServiceDown

## What this alert means

Prometheus cannot scrape a monitored service. The alert labels identify the
service namespace, deployment, and scrape job.

## Investigation

1. Check the deployment's available replicas and recent rollout status.
2. Inspect pod readiness, recent restarts, and Kubernetes events.
3. Check service endpoints and the pod's readiness probe.
4. Compare the most recent deployment change with the first failed scrape.

## Safe response

Do not restart or scale solely because a scrape failed. Confirm the deployment
and target are healthy first. Use the incident approval endpoint only when the
model suggests an allow-listed action for a supported target.
