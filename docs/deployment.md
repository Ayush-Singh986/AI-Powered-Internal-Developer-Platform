# Deployment guide

The local demo needs Docker Compose only. kind and EKS deploy the same
GitOps-managed application definitions; they differ only in the service
overlay, storage, ingress values, and cluster-specific sealed-secret files.
No Helm chart is installed manually: Argo CD installs the pinned charts.

## 1. No-key local demo

Install Docker Desktop with Compose v2, Git, GNU Make, and Bash. From the
project directory:

1. Start the stack with `make demo`. Compose builds the services and starts the
   mock OpenAI-compatible provider, which returns `DEMO MODE: canned answer`.
   It does not need an external LLM key.
2. Visit <http://localhost:8501> for the portal and
   <http://localhost:3000> for Grafana (`admin` / `demo-only-password`). All
   Compose-published ports bind to `127.0.0.1`.
3. Run `make demo-alert` to submit a synthetic Alertmanager alert to the agent.
   Refresh the portal to see the incident generated through the application.
4. Run `make test` for service unit tests and the isolated end-to-end Compose
   smoke test. The smoke test uses a separate temporary project and cleans up
   its own volumes.
5. Stop the demo with `make demo-down`.

For a real provider in Compose, copy `.env.example` to `.env`, set the
provider URL/model/key, a strong Grafana password, `SERVICE_AUTH_TOKEN`,
`AIOPS_ACTION_TOKEN`, and a positive `DAILY_TOKEN_LIMIT`. Keep `.env`
untracked. Compose refuses to start Grafana when its password is empty.

## 2. Deploy to local Kubernetes with kind and Argo CD

### Prerequisites and repository access

Install Docker, kind, kubectl, Kustomize, GNU Make, kubeseal, and Git. Run
commands from Git Bash or WSL on Windows. A public GitHub repository works
without extra Argo CD credentials. A private repository requires configuring
an SSH deploy key or a repository-scoped token in Argo CD before bootstrap.

### One-time GitOps repository configuration

Use your platform repository's actual owner/name:

```bash
scripts/set-repo.sh OWNER/PLATFORM_REPO
git add argocd
git commit -m "chore: configure Argo CD repository"
git push
```

Argo CD needs to fetch this committed configuration, so push it before the
first cluster setup. If `make kind-up` finds that this configuration still
needs changing, it updates the local files, prints the reason, and exits; push
the change and rerun the target.

### Prepare credentials and launch

kind runs the model adapter against the canned mock provider. No paid LLM key
is needed. The sealed `LLM_API_KEY` is empty in this demo mode. Enter strong
service, action, and Grafana credentials in the shell that will run Make:

```bash
read -r -s -p "Shared service token: " SERVICE_AUTH_TOKEN; printf '\n'; export SERVICE_AUTH_TOKEN
read -r -s -p "Action approval token: " AIOPS_ACTION_TOKEN; printf '\n'; export AIOPS_ACTION_TOKEN
read -r -s -p "Grafana password: " GRAFANA_ADMIN_PASSWORD; printf '\n'; export GRAFANA_ADMIN_PASSWORD
```

Now run the single setup target, substituting the repository's real owner and
name:

```bash
make kind-up REPO=OWNER/PLATFORM_REPO
```

The script bootstraps the `aiops-local` kind cluster and pinned Argo CD `v3.5.6`,
waits for the Sealed Secrets controller, generates cluster-bound encrypted
credentials, builds and loads the five application images plus the mock LLM,
and updates the kind image overlays. The `v3.5.6` Argo CD release exists; this
installation and these manifests have not yet been runtime-tested in this
environment.

`kind-up` does not commit or push to your branch. Review and push the generated
GitOps state together:

```bash
git add k8s/sealed-secrets/kind k8s/overlays/kind
git commit -m "chore: prepare kind deployment"
git push
```

Argo CD will reconcile the pushed manifests. Wait for all service and
infrastructure applications to become Healthy and Synced, then check:

```bash
kubectl get applications -n argocd
kubectl get pods -A
kubectl get ingress -A
kubectl get networkpolicy -A
```

Only the portal and Grafana should have Ingress routes. Add
`127.0.0.1 aiops.local` to the Windows hosts file to open
<http://aiops.local> and <http://aiops.local/grafana>. kind's default CNI does
not enforce NetworkPolicies; enforcement has not been tested on kind or EKS.
The EKS Terraform configuration sets the VPC CNI network-policy option, but
that configuration is not proof of enforcement.

Delete the local cluster when finished:

```bash
kind delete cluster --name aiops-local
```

### Troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| Argo CD reports repository not found or authentication failed | Wrong `OWNER/PLATFORM_REPO`, or the GitHub repo is private | Check every `repoURL` under `argocd/`. For a private repo, configure its deploy key or token in Argo CD. |
| Pods show `ImagePullBackOff` | Overlay changes were not pushed, or the image tag was not loaded into kind | Run `make kind-deploy`, commit/push `k8s/overlays/kind/`, and check `kubectl describe pod -n <namespace> <pod>`. |
| Pods show `CreateContainerConfigError` or a SealedSecret stays unready | Required secret is missing, from a different cluster key, or Argo CD has not synced it | Check the relevant SealedSecret and `kubectl describe pod`; regenerate secrets for this cluster and push `k8s/sealed-secrets/kind/`. |

## 3. Deploy to AWS EKS

### Prepare and apply Terraform

Use Terraform `>=1.10`, AWS CLI, an AWS identity authorized for the
Terraform-managed VPC, EKS, ECR, IAM, and CSI resources, and a restricted
operator CIDR. Create a private, versioned, encrypted S3 bucket before
initializing remote state. Example Bash:

```bash
export AWS_REGION=us-east-1
export TF_STATE_BUCKET=replace-with-globally-unique-private-bucket
aws s3api create-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION"
aws s3api put-public-access-block --bucket "$TF_STATE_BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$TF_STATE_BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$TF_STATE_BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
cp terraform/backend.hcl.example terraform/backend.hcl
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit the backend bucket, region, EKS version, node type, and operator CIDR.
terraform -chdir=terraform init -backend-config=backend.hcl
terraform -chdir=terraform validate
terraform -chdir=terraform plan
terraform -chdir=terraform apply
```

**PowerShell**

```powershell
$env:AWS_REGION = "us-east-1"
$env:TF_STATE_BUCKET = "replace-with-globally-unique-private-bucket"
aws s3api create-bucket --bucket $env:TF_STATE_BUCKET --region $env:AWS_REGION
aws s3api put-public-access-block --bucket $env:TF_STATE_BUCKET `
  --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws s3api put-bucket-versioning --bucket $env:TF_STATE_BUCKET `
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket $env:TF_STATE_BUCKET `
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
Copy-Item terraform/backend.hcl.example terraform/backend.hcl
Copy-Item terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit the backend bucket, region, EKS version, node type, and operator CIDR.
terraform -chdir=terraform init -backend-config=backend.hcl
terraform -chdir=terraform validate
terraform -chdir=terraform plan
terraform -chdir=terraform apply
```

Confirm the EKS Kubernetes version is still supported in your region before
applying. Workers use public subnets without NAT to reduce demo baseline cost;
this is not a production network design. A public ingress load balancer,
nodes, persistent volumes, image storage, and data transfer can still incur
charges. The VPC CNI add-on is configured to enable NetworkPolicies.

### Publish images and bootstrap Argo CD

Configure these repository **Actions variables**:

| Name | Value |
|---|---|
| `AWS_REGION` | The Terraform region. |
| `AWS_PROJECT_NAME` | The same value as `project_name` in `terraform.tfvars`. |
| `AWS_ENVIRONMENT` | The same value as `environment` in `terraform.tfvars`. |
| `TF_STATE_BUCKET` | The private S3 bucket used for Terraform state. |
| `CLUSTER_ADMIN_CIDRS` | A Terraform list of allowed operator CIDRs, e.g. `["203.0.113.10/32"]`. |

Add the repository **Actions secret** `AWS_TERRAFORM_ROLE_ARN` with the ARN
of an IAM role configured for GitHub Actions OIDC. Restrict its trust policy
to this repository and the intended branch/workflows; grant only the S3 state
and ECR permissions the workflows need. Do not add long-lived AWS access
keys. The Terraform pull-request workflow also assumes this role, so its
`pull_request` OIDC subject must be trusted if that workflow is enabled. Since
the role can publish ECR images, only allow trusted pull requests or use a
separate read-only role for Terraform plans.

Each service workflow tests, scans, and publishes a commit-SHA image to ECR,
then commits the new image reference to `k8s/base/`. To publish the initial
images after creating the ECR repositories, manually run each `Build ...`
workflow on branch `main` from GitHub Actions: AIOps agent, LLM gateway,
model serving, portal, and RAG. The workflows also run on service-source
pushes to `main`. Their push filters do not match `k8s/**`-only commits, and
the GitOps manifest commits are marked `[skip ci]`.

Configure the repo URL once with the platform repository's actual owner and
name, then commit and push:

```bash
scripts/set-repo.sh OWNER/PLATFORM_REPO
git add argocd
git commit -m "chore: configure Argo CD repository"
git push
cluster="$(terraform -chdir=terraform output -raw cluster_name)"
region="$(terraform -chdir=terraform output -raw cluster_region)"
aws eks update-kubeconfig --name "$cluster" --region "$region"
kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.6/manifests/install.yaml
kubectl -n argocd rollout status deployment/argocd-server --timeout=5m
kubectl apply -f argocd/root-application.yaml
```

This is the same fixed Argo CD `v3.5.6` install method as kind, followed by
one root-Application bootstrap. Wait for the Argo-managed Sealed Secrets
controller, then enter credentials without putting them in shell history or
Git:

```bash
read -r -s -p "Provider API key: " LLM_API_KEY; printf '\n'; export LLM_API_KEY
read -r -s -p "Shared service token: " SERVICE_AUTH_TOKEN; printf '\n'; export SERVICE_AUTH_TOKEN
read -r -s -p "Action approval token: " AIOPS_ACTION_TOKEN; printf '\n'; export AIOPS_ACTION_TOKEN
read -r -s -p "Grafana password: " GRAFANA_ADMIN_PASSWORD; printf '\n'; export GRAFANA_ADMIN_PASSWORD
scripts/seal-secrets.sh eks
git add k8s/sealed-secrets/eks
git commit -m "chore: add EKS sealed secrets"
git push
```

Commit only `k8s/sealed-secrets/eks/*.yaml` and its generated
`kustomization.yaml`; never commit the plaintext credentials. Sealed values
from kind cannot be reused on EKS. A public GitHub repository works without
extra configuration; a private repository requires an SSH deploy key or
repository-scoped token configured securely in Argo CD before root bootstrap.

The EKS ingress controller creates a LoadBalancer. Configure DNS/TLS before
exposing the portal. Grafana reads its password from the sealed
`grafana-admin` Secret. If using AWS Secrets Manager instead, implement and
install External Secrets Operator and change the workload references; that
alternative is not configured in this scaffold.

### Verify and tear down

After all Apps report Healthy/Synced, verify routes, resources, metrics, and
security checks as described in [security.md](security.md). Capture `kubectl
get pods -A`, `kubectl top pods -A`, and restart counts while a representative
load runs for 30 minutes. Save real values to `docs/results.csv`.

Destroy the demo infrastructure when finished:

```bash
make eks-destroy
```

Terraform's remote state bucket is separate and is intentionally retained.
Confirm EKS, EC2, load balancers, EBS volumes, and ECR storage are gone in AWS
before deciding whether to delete the bucket. No destroy was run for this
project.
