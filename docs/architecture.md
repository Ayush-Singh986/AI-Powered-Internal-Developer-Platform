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

    AM->>Agent: Authenticated firing/resolved alert
    Agent->>DB: Deduplicate and durably queue
    Agent-->>AM: HTTP 202 after commit
    Agent->>DB: Claim ready diagnosis job
    opt Evidence namespace explicitly enabled
        Agent->>K8s: Read bounded logs, events, rollout facts
    end
    Agent->>Runs: Retrieve by alert name (best-effort)
    Runs-->>Agent: Ranked runbook excerpts
    Agent->>DB: Reserve one LLM call within hourly cap
    Agent->>Gateway: Minimal alert context and optional evidence
    Gateway->>DB: Atomically reserve global/client token budget
    Gateway->>Model: Authenticated completion request
    Model->>Provider: OpenAI-compatible request
    Provider-->>Model: Structured suggestion and usage
    Model-->>Gateway: Completion and provider token count
    Gateway->>DB: Settle token reservation
    Gateway-->>Agent: Cause/action/confidence JSON
    Agent->>DB: Save suggestion and pending decision
    Portal->>Agent: Authenticated paginated incident request
    Agent-->>Portal: Summary and suggestion; evidence omitted
    Portal->>Agent: Explicit evidence reveal
    Agent-->>Portal: Evidence only after user request
    Portal->>Agent: Authenticated human action approval
    Agent->>K8s: Allow-listed action on approved target
    Agent->>DB: Persist approval and action result
```

## Components and trust boundaries

| Component | Input | State and controls |
|---|---|---|
| Runbook retrieval | Authenticated query from the agent. | Bundled Markdown documents; alert-name mapping plus deterministic lexical ranking. |
| Model adapter | Authenticated request from the gateway. | Provider URL/model/API key are runtime config; no model weights are served locally. |
| LLM gateway | Authenticated named clients (agent and portal). | SQLite atomic global/per-client token reservations, request rate, bounded prompt/output sizes; process-local per-caller response cache. |
| AIOps agent | Dedicated Alertmanager webhook token; separate portal/action credentials. | SQLite durable jobs, fingerprint dedupe, bounded retries, optional evidence, resolved timestamps, retention, saved model suggestions/decisions. |
| Operations portal | Internal service health checks; authenticated incident feed and action approval. | Evidence omitted until explicit reveal; no provider or action secret is sent to the browser. |
| Argo CD | Git desired state and pinned Helm chart versions. | Auto-sync/self-heal for application and infrastructure resources. |

The Kubernetes manifests keep the completion service, gateway, runbook
retrieval, and agent internal. Only the portal and Grafana have Ingress
resources. NetworkPolicy manifests express service ingress and egress, but
policy enforcement has not been tested on kind or EKS. kind's default CNI does
not enforce them; the EKS Terraform configuration opts in to VPC CNI policy
support but still requires runtime tests. The model-adapter health badge is
fetched through the authenticated gateway, so the portal does not connect
directly to the adapter.

The local Compose demo and kind overlay use the canned mock provider. The
model adapter uses the configured OpenAI-compatible provider in EKS.

Evidence collection is disabled unless `EVIDENCE_ENABLED_NAMESPACES` lists an
approved namespace. When enabled, the agent reads only the last 50 log lines
per selected pod, up to 20 deployment pods, and up to 20 recent events. It
reads the Deployment's current image references, rollout revision, and recent
conditions. Sensitive key/value pairs and common bearer/provider token
patterns are best-effort redacted; serialized context is length-capped. The
model is instructed that alert, log, event, and runbook text are untrusted
data, and its actions remain suggestions pending human approval.

## Delivery loop

1. A service workflow runs its unit tests, builds an image, and scans it with
   Trivy.
2. On a `main` push, CI publishes an immutable commit-SHA image to ECR and
   opens a pull request that updates the service's Kubernetes manifest to the
   image digest. An operator reviews and merges that GitOps change.
3. Argo CD watches Git and reconciles the desired workload.
