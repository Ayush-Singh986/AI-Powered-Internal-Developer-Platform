.PHONY: up down build logs test lint fmt \
        kind-up tf-init tf-plan tf-apply \
        argocd-bootstrap local-check

# ─── Local (docker compose) ───────────────────────────────────────────────────

up:              ## Build images and start everything locally
	docker compose up --build

down:            ## Stop and remove containers + volumes
	docker compose down -v

build:           ## Build all images without starting
	docker compose build

logs:            ## Follow logs from all containers
	docker compose logs -f

local-check:     ## Quick smoke test — hit /healthz on the portal and backend services
	@echo "=== portal ===" && curl -sf http://localhost:8501/healthz
	@echo "=== docs-assistant ===" && curl -sf http://localhost:8001/healthz
	@echo "=== model-serving ===" && curl -sf http://localhost:8002/healthz
	@echo "=== llm-gateway ===" && curl -sf http://localhost:8003/healthz
	@echo "=== aiops-agent ===" && curl -sf http://localhost:8004/healthz
	@echo "\nAll services healthy."

# ─── Tests & Linting ──────────────────────────────────────────────────────────

test:            ## Install dev deps and run pytest
	pip install -q -r requirements-dev.txt && pytest -q tests

lint:            ## Run ruff linter
	ruff check services/ tests/

fmt:             ## Format code with black
	black services/ tests/

# ─── Local Kubernetes + ArgoCD ────────────────────────────────────────────────

kind-up:         ## Create a local kind cluster and bootstrap ArgoCD + root app
	kind create cluster --name idp
	kubectl create namespace argocd
	kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
	kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
	kubectl apply -f gitops/bootstrap/root.yaml

argocd-bootstrap:  ## Apply ArgoCD root app-of-apps to an existing cluster
	kubectl apply -f gitops/bootstrap/root.yaml

# ─── Terraform ────────────────────────────────────────────────────────────────

tf-init:         ## terraform init in envs/dev
	cd terraform/envs/dev && terraform init

tf-plan:         ## terraform plan in envs/dev
	cd terraform/envs/dev && terraform init && terraform plan

tf-apply:        ## terraform apply in envs/dev (requires confirmation)
	cd terraform/envs/dev && terraform init && terraform apply

help:            ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
