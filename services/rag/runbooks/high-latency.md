# Elevated request latency

## What to inspect

Compare request rate, error rate, and p95 latency. Check pod saturation, recent
deployments, upstream dependency latency, and gateway/model-provider response
time.

## Safe first response

If replicas are saturated and the workload has capacity, scaling the deployment
may help. Verify the change against the service's resource limits and observe
latency and errors after the change.
