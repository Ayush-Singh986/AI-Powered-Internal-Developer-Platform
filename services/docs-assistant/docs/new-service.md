# Adding a new service

## Steps
Create a folder under services with a Dockerfile. Call instrument(app, name) from the common package so you get metrics and health checks for free. Add a folder under gitops/manifests and an Application file under gitops/apps. Merge to main and ArgoCD creates the namespace and deploys it.

## Cost control
Never call an LLM provider directly. Send requests to the llm-gateway so cost, tokens and caching are tracked in one place.
