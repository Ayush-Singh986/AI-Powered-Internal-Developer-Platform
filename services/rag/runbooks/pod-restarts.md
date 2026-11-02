# Repeated pod restarts

## What to inspect

Check the pod's previous container logs, termination reason, recent events, and
the deployment's resource requests and limits. `CrashLoopBackOff` is a symptom,
not a root cause.

## Safe first response

Confirm whether a rollout or configuration change preceded the restarts. Check
memory and CPU pressure before changing resource allocations. Restarting a
healthy workload repeatedly can hide the original failure.
