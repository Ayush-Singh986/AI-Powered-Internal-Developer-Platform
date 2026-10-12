# On-call guide

## First 10 minutes of an incident
Check the Mission Control dashboard in Grafana for error rate and latency by service. Look at the Incident Feed in the portal to see if the AIOps agent already acted. Check the last deploy in ArgoCD, since most incidents follow a deploy.

## Escalation
If the error rate stays above 20 percent after a restart, page the service owner and consider a rollback.

## Auto-remediation
The AIOps agent restarts a deployment when error rate or p95 latency stays above the threshold. It waits 5 minutes between restarts of the same service.
