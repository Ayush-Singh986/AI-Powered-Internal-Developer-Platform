# ContainerOOMKilled

## What this alert means

A monitored container was terminated after exceeding its memory limit.

## Investigation

1. Check the container's memory limit, recent usage, and workload changes.
2. Inspect pod events and the previous container's termination details.
3. Compare memory usage with request volume and recent deployments.
4. Check for an unbounded queue, cache, or batch size before changing limits.

## Safe response

Do not repeatedly restart the pod or increase limits without checking node
capacity and workload behavior. Reduce load or correct the memory growth cause.
