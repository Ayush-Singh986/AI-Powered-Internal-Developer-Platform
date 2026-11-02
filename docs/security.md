# Security, data handling, and operational limits

## Authentication and authorization

- Each internal caller uses a distinct credential: `RAG_SERVICE_TOKEN`,
  `MODEL_SERVICE_API_KEY`, `LLM_GATEWAY_API_KEY`, `PORTAL_GATEWAY_API_KEY`,
  `AGENT_SERVICE_TOKEN`, `AIOPS_ACTION_TOKEN`, and
  `ALERTMANAGER_WEBHOOK_TOKEN`. Rotate them independently. Alertmanager alone
  uses the webhook token; possession of another service token cannot submit
  alerts.
- The gateway authenticates named clients from `LLM_GATEWAY_CLIENT_KEYS`
  (JSON mapping caller names to tokens). It enforces global and per-client
  daily token budgets, a per-client request rate, bounded prompt/output sizes,
  and atomic pre-call token reservations.
- The portal's Kubernetes Ingress is protected by OAuth2 Proxy and TLS. The
  OIDC issuer, client credentials, cookie secret, and TLS certificate are
  external deployment prerequisites. The local Compose portal is loopback-only
  and is not an identity provider.
- Kubernetes remediation is disabled on alert ingestion. The model returns a
  structured cause/action/confidence suggestion. The agent accepts only
  allow-listed suggestions for known alert/target pairs; an operator must
  approve the exact suggestion using the separate action token. Approved
  decisions and outcomes are persisted. The agent's Kubernetes RBAC is limited
  to the `rag` deployment, and its allow-list reflects that boundary.
- The portal incident list is paginated and omits evidence by default.
  Evidence is fetched only after an operator explicitly reveals it. Resolved
  incidents and their jobs are deleted after 90 days; active incidents are
  retained.

## Alert and model reliability

- `/alerts` validates and durably stores a bounded payload in SQLite before
  returning HTTP `202`. A single worker resumes jobs after restart, retries
  failed diagnoses with bounded exponential delay, and marks a job failed
  after five attempts. Resolved notifications close incidents and cancel
  pending work; a later firing notification can open a new incident.
- Runbook retrieval is selected by alert name and is best-effort. A RAG
  outage does not prevent model diagnosis. Model/provider failures are retried
  by the worker rather than holding Alertmanager's webhook open.
- Alertmanager sends resolved notifications. `ServiceDown` includes namespace
  and deployment labels. The Prometheus configuration has error-rate, p95
  latency, restart, OOM, and Watchdog rules.
- Alertmanager's default route notifies the agent only. The optional external
  receiver is intentionally disabled until an operator mounts a valid
  webhook-URL secret and enables the external labels/routes. Enable the
  Watchdog route only after verifying the external heartbeat receiver; a local
  Watchdog alert is not proof that an external pager is reachable.
- The gateway retries connection failures twice and can use
  `MODEL_FALLBACK_URL` when configured. It does not retry ambiguous timeouts or
  provider HTTP errors, avoiding accidental duplicate charges. Successful
  responses are cached only in bounded process memory, per caller, for 30
  seconds; prompts/responses are not persisted by the cache.

## Data policy

Alert names, bounded/redacted summaries, namespace/deployment labels, and
matching runbook excerpts are sent to the configured model endpoint. Raw pod
logs and Kubernetes events are **not collected by default**. Set
`EVIDENCE_ENABLED_NAMESPACES` only to explicitly approved namespaces to enable
their collection and model submission. Collected evidence is truncated and
best-effort redacted, but redaction cannot guarantee removal of secrets or
personal/customer data. Review the content and provider retention, training,
region, and contractual policy before enabling evidence or sending production
alerts to an external provider.

For sensitive environments, point `LLM_BASE_URL` at a compatible model
endpoint inside the approved network and leave the provider key empty when
that endpoint does not require one. Verify that endpoint's data handling before
use. No model provider is configured by this repository.

## Network and infrastructure boundaries

- Service NetworkPolicies now define ingress and egress for the app pods.
  The model adapter requires outbound TCP/443 to reach a provider; the agent
  allows TCP/443 and TCP/6443 for Kubernetes API access. Those generic
  `ipBlock` rules are broader than a provider/control-plane CIDR allow-list;
  replace them with cluster/provider-specific rules before production.
- kind's default CNI does not enforce NetworkPolicies. EKS VPC CNI policy
  enforcement must be enabled and verified with live connectivity tests.
- SQLite is for a single replica. The agent and gateway use one replica and
  `strategy: Recreate` with persistent volumes to avoid overlapping mounts.
  Do not scale them horizontally; migrate incident and budget data to a
  multi-writer database before doing so.
- The OAuth2 Proxy credentials, TLS secret, external webhook URL, and
  per-cluster sealed secrets must be provisioned by the operator. Sealed
  Secrets are cluster-bound. EKS External Secrets Operator integration is not
  configured.
- The Terraform footprint, node sizing, EKS budget alarms, and cost envelope
  have not been validated against measured workload data. Run a representative
  load test and configure AWS budgets before production use.

## Automated checks and remaining acceptance

`make test` runs service unit tests, monitoring configuration tests, and the
Compose smoke test. These tests do not prove Kubernetes RBAC, NetworkPolicy
enforcement, OIDC/TLS configuration, external paging, or diagnosis quality on
a real workload. Docker/kind/EKS validation must be run in an environment with
those tools and credentials.

Distributed OpenTelemetry tracing is not wired across the webhook, persisted
worker, runbook, model, and action path. The known-failure evaluation in item 3
is also an operator-run acceptance gate, not an automated scoring harness.

Before calling this production-ready:

1. Run kind integration checks that kill a pod and verify captured evidence,
   resolved-alert behavior, human approvals, and the portal's authenticated
   evidence reveal.
2. Verify Alertmanager matcher strategy and the external Watchdog heartbeat
   against a real receiver; page a human if the agent or model provider is
   unavailable.
3. Inject at least 15 known failures, score cause/action suggestions with and
   without evidence, and record operator feedback.
4. Measure node/resource usage and monthly provider/AWS costs; test expected
   and 10x alert volume.
5. Restrict model/API egress to provider and control-plane address ranges, and
   verify policies on the actual CNI.
6. Document token rotation and the approved external-model data policy for the
   operating team.
