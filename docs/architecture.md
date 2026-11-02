# Architecture and behavior

## Request and alert flow

```mermaid
sequenceDiagram
    participant AM as Alertmanager
    participant Agent as AIOps agent
    participant K8s as Kubernetes API
    participant Runs as Runbook retrieval
    participant Gateway as LLM gateway
    participant Model as Model adapter
    participant Provider as Configured provider
    participant DB as SQLite
    participant Portal as Operations portal

    AM->>Agent: Authenticated firing alert with fingerprint
    Agent->>DB: Look up open incident by fingerprint
    alt Existing open incident
        Agent->>K8s: Refresh bounded logs, events, rollout facts
        Agent->>DB: Update same incident and evidence
    else New incident
        Agent->>K8s: Read recent logs, events, deployment image/revision
        Agent->>Runs: Retrieve relevant Markdown procedures
        Runs-->>Agent: Ranked runbook excerpts
        Agent->>DB: Reserve one LLM call within hourly cap
        Agent->>Gateway: Authenticated evidence and runbook context
        Gateway->>DB: Check UTC daily token budget
        Gateway->>Model: Authenticated completion request
        Model->>Provider: OpenAI-compatible request
        Provider-->>Model: Diagnosis and usage
        Model-->>Gateway: Completion and provider token count
        Gateway->>DB: Persist token usage and configured cost estimate
        Gateway-->>Agent: Diagnosis
        Agent->>DB: Store incident and evidence
    end
    Portal->>Agent: Authenticated incident-feed request
    Agent-->>Portal: Incident details, evidence, and action audit
```

## Components and trust boundaries

| Component | Input | State and controls |
|---|---|---|
| Runbook retrieval | Authenticated query from the agent. | Bundled Markdown documents; deterministic lexical ranking. |
| Model adapter | Authenticated request from the gateway. | Provider URL/model/API key are runtime config; no model weights are served locally. |
| LLM gateway | Authenticated requests from the agent and portal health check. | SQLite UTC daily token total; provider-usage token metrics; cost estimate only when both pricing rates are set. |
| AIOps agent | Authenticated Alertmanager webhook; authenticated portal feed and operator action. | SQLite incidents, fingerprint dedupe, evidence, hourly LLM reservations, timestamped action audit. |
| Operations portal | Internal service health checks; authenticated incident feed. | No provider or action secret is sent to the browser. |
| Argo CD | Git desired state and pinned Helm chart versions. | Auto-sync/self-heal for application and infrastructure resources. |

The Kubernetes manifests keep the completion service, gateway, runbook
retrieval, and agent internal. Only the portal and Grafana have Ingress
resources. NetworkPolicy manifests express the intended service paths, but
policy enforcement has not been tested on kind or EKS. kind's default CNI does
not enforce them; the EKS Terraform configuration opts in to VPC CNI policy
support but still requires a runtime enforcement test. The model-adapter
health badge is fetched through an authenticated gateway dependency endpoint,
so the portal does not connect directly to the adapter.

The local Compose demo and kind overlay use the canned mock provider. The
model adapter uses the external configured provider in an EKS deployment.

The agent reads only the last 50 log lines per selected pod, up to 20
deployment pods, and up to 20 recent events. It reads the Deployment's current
image references, rollout revision, and most recent condition time. Sensitive
key/value pairs and common bearer/provider token patterns are redacted; the
serialized prompt context is length-capped. The model is instructed that alert,
log, event, and runbook text are untrusted data and never executable
instructions.

## Delivery loop

1. A service workflow runs its unit tests, builds an image, and scans it with
   Trivy.
2. On a `main` push, CI publishes an immutable commit-SHA image to ECR and
   commits the new image reference to that service's Kubernetes manifest.
   The bot commit includes `[skip ci]`; the service workflows also filter their
   push paths to service/workflow sources, not `k8s/**`.
3. Argo CD watches the Git revision and reconciles the desired workload.
4. Prometheus scrapes `/metrics`, evaluates health rules, and routes alerts to
   the authenticated agent webhook.

The five application service Applications use sync wave 1 and
`CreateNamespace=true`. Ingress, monitoring, metrics-server, and Sealed
Secrets controller Applications use wave 0. Service-specific sealed values
are cluster-bound and generated only after that cluster's Sealed Secrets
controller is available.
