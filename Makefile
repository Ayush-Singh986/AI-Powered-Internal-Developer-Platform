.PHONY: demo demo-alert demo-down test kind kind-up kind-deploy eks-destroy

demo:
	bash scripts/demo-up.sh

demo-alert:
	bash scripts/demo-alert.sh

demo-down:
	bash scripts/demo-down.sh

test:
	bash -c 'set -e; for service in rag model-serving llm-gateway aiops-agent; do (cd services/$$service && python -m unittest discover -s . -p "test_*.py" -v); done'
	bash scripts/smoke-test.sh

kind:
	bash scripts/kind-bootstrap.sh

kind-up:
	bash scripts/kind-up.sh "$(REPO)"

kind-deploy:
	bash scripts/kind-deploy.sh

eks-destroy:
	terraform -chdir=terraform destroy
