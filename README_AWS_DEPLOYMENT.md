# Run the Project on AWS: Step-by-Step

This guide takes the project from a GitHub checkout to running services on AWS EKS. Commands are written for Bash on Linux or WSL. Docker Compose and `kind` are not used for this AWS deployment.

> **Cost and security:** Terraform creates paid AWS resources, including EKS, EC2 worker nodes, networking, and NAT. Review every Terraform plan and your AWS budget before applying it. This is a learning-project setup, not a production security blueprint. Do not put access keys, tokens, or passwords in Git.

## What you will set up

- AWS VPC, EKS cluster, and S3 artifact bucket using Terraform.
- Jenkins, hosted and configured separately from this repository.
- Container images stored in GitHub Container Registry (GHCR).
- Argo CD, which reads the Git deployment files and updates the AWS EKS applications.
- Five application services, Prometheus, and Grafana inside EKS.

### AWS infrastructure created by Terraform

The development Terraform configuration creates the following AWS infrastructure in `ap-south-1` by default:

| AWS resource | Configuration |
| --- | --- |
| VPC and networking | `idp-dev` VPC with CIDR `10.20.0.0/16`, public and private subnets across `ap-south-1a` and `ap-south-1b`, and one shared NAT gateway for private-subnet egress. |
| Amazon EKS | EKS cluster named `idp-dev`, running Kubernetes `1.35`, with its API endpoint publicly reachable by default. Restrict the endpoint to trusted IPs before applying, as described in step 3. |
| EC2 worker nodes | EKS-managed node group in the private subnets. It defaults to two `t3.large` instances, with autoscaling bounds of one to four nodes. The node count and instance type can be changed in the cluster module inputs. |
| Amazon S3 | One artifact bucket whose globally unique name you provide. Versioning and AES-256 server-side encryption are enabled, and all forms of public access are blocked. |

The EKS control plane is managed by AWS; the worker nodes are EC2 instances. EKS, EC2, NAT Gateway, and data transfer may incur charges. Review the Terraform plan and AWS pricing before applying it.

Jenkins, GHCR, Argo CD, the application services, Prometheus, and Grafana are not all Terraform-created AWS resources: Jenkins is installed separately, GHCR is hosted by GitHub, and Argo CD plus the application and monitoring workloads are installed into EKS in later steps. This Terraform configuration does not create an internet-facing application load balancer, database, or Jenkins EC2 instance.

## 1. Install and check the command-line tools

Install these tools on your administrator workstation or AWS management host:

- Git, AWS CLI v2, Terraform 1.6 or newer, `kubectl`, Helm 3, and `openssl`.
- A GitHub account with permission to push to the repository.
- An AWS account and an AWS identity allowed to create the VPC, EKS, EC2, IAM, and S3 resources in this project.

Check that the tools are available:

```bash
git --version
aws --version
terraform version
kubectl version --client
helm version
```

Docker is required on the Jenkins build agent, not on the administrator workstation or AWS EKS worker nodes.

## 2. Clone your GitHub repository and set its name

Use your own fork URL if you forked this project. The example below uses the project repository:

```bash
git clone https://github.com/Ayush-Singh986/AI-Powered-Internal-Developer-Platform.git
cd AI-Powered-Internal-Developer-Platform

# Set these to the owner and exact repository name in your GitHub URL.
export GITHUB_OWNER="your-github-username"
export GITHUB_REPO="AI-Powered-Internal-Developer-Platform"
export IMAGE_NAMESPACE="$(printf '%s' "$GITHUB_OWNER" | tr '[:upper:]' '[:lower:]')"
```

The GitOps application files contain example GitHub repository and GHCR owner names. Replace them with your repository details:

```bash
find gitops -type f -name '*.yaml' -exec sed -i \
  "s#YOUR_GITHUB_USER#${GITHUB_OWNER}#g; s#ghcr.io/${GITHUB_OWNER}#ghcr.io/${IMAGE_NAMESPACE}#g; s#https://github.com/${GITHUB_OWNER}/ai-idp.git#https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}.git#g" \
  {} +

# Confirm that no example GitHub owner or old repository URL remains.
if grep -R -n -E 'YOUR_GITHUB_USER|/ai-idp\.git' gitops; then
  echo "Update the remaining GitOps repository placeholders before continuing."
  exit 1
fi

git add gitops
git commit -m "docs/ops: configure GitOps repository"
git push origin main
```

If you cloned a fork, make sure `origin` points to your fork before pushing:

```bash
git remote -v
```

## 3. Configure and verify AWS access

Configure an AWS CLI profile using your organization's approved AWS credentials. The command prompts for credentials; do not paste credentials into this README or a shell script.

```bash
aws configure --profile idp-dev
export AWS_PROFILE=idp-dev
export AWS_REGION=ap-south-1

aws sts get-caller-identity
```

The identity check must succeed before you create infrastructure. The selected identity also needs permission to pass or create the IAM roles required by EKS.

The EKS API endpoint is public in the current Terraform configuration. Before applying it, restrict the endpoint to your administrator IP by adding this setting to the `module "eks"` block in `terraform/modules/cluster/main.tf`:

```hcl
cluster_endpoint_public_access_cidrs = ["YOUR_PUBLIC_IP/32"]
```

Replace `YOUR_PUBLIC_IP` with your public IPv4 address. Do not leave a broad public API allowlist for a real deployment.

## 4. Create the AWS infrastructure with Terraform

The checked-in Terraform configuration creates the `idp-dev` EKS cluster in `ap-south-1`, its VPC and subnets, and an S3 bucket. The cluster is configured for Kubernetes 1.35.

Choose a globally unique, lowercase S3 bucket name. The shortened owner name and timestamp keep it within S3's bucket-name length limit and help avoid a collision:

```bash
export BUCKET_OWNER="$(printf '%s' "$IMAGE_NAMESPACE" | cut -c1-32)"
export ARTIFACT_BUCKET="idp-artifacts-${BUCKET_OWNER}-$(date +%s)"
```

Review the plan, then apply that reviewed plan:

```bash
cd terraform/envs/dev
terraform init
terraform validate
terraform plan -out=tfplan \
  -var="region=${AWS_REGION}" \
  -var="artifact_bucket=${ARTIFACT_BUCKET}"

# Read the plan output above before confirming this creates paid resources.
terraform apply tfplan
cd ../../..
```

Terraform state is currently stored locally in this working copy. Back it up securely and do not commit it. For shared/team use, configure a protected remote Terraform backend and state locking before provisioning.

## 5. Connect `kubectl` to the new EKS cluster

```bash
aws eks update-kubeconfig \
  --name idp-dev \
  --region "$AWS_REGION"

kubectl get nodes
kubectl get namespaces
```

Wait until the worker nodes show `Ready` before continuing.

## 6. Set up Jenkins and run the image pipeline

Jenkins is **not installed by this repository's Terraform**. Set up Jenkins separately, preferably on an AWS-hosted Linux machine or an approved managed Jenkins service. For webhook builds, GitHub needs a secure HTTPS route to the Jenkins webhook endpoint; if you cannot provide one, use periodic branch indexing instead. Protect the Jenkins controller with HTTPS and access controls.

Install these plugins on the Jenkins controller:

- Pipeline, Git, GitHub Branch Source, and Credentials Binding.
- Configure the Jenkins Git installation with the name `Default`.

The Linux Jenkins build agent needs:

- Git, Python 3.12, Node.js 22 with npm, Docker CLI connected to a working Docker daemon, and Trivy.

Check the agent tools before the first build:

```bash
git --version
python3 --version
node --version
npm --version
docker info
trivy --version
```

In Jenkins:

1. Create a **Multibranch Pipeline** for your GitHub repository and point it to the repository's `Jenkinsfile`.
2. Configure GitHub branch discovery, including pull requests if you want pull-request test runs.
3. Configure a GitHub webhook to Jenkins, or enable periodic branch indexing if a webhook cannot reach Jenkins.
4. Add a username/password credential named `ghcr-credentials`. Use your GitHub username and a token with permission to publish packages to GHCR (for a classic personal access token, grant `write:packages`).
5. Add a username/password credential named `github-push-credentials`. Use your GitHub username and a token with permission to push commits to this repository's `main` branch (for a classic personal access token, grant `repo`).
6. Run or scan the `main` branch and set its `IMAGE_NAMESPACE` parameter to the actual lowercase GitHub user or organization name (for example, type `my-github-user`, not the literal text `$IMAGE_NAMESPACE`). The checked-in Jenkinsfile defaults this parameter to `Ayush-Singh986`; if you use a fork, change the default or override it with your fork owner's name before building.

The `Jenkinsfile` runs tests and builds the portal bundle on branches and pull requests. On `main`, it also builds five service images, pushes them to GHCR, runs a report-only Trivy scan, updates the GitOps image tags, and pushes the tag update to GitHub. A `[skip ci]` commit marker prevents the tag update from starting a build loop.

Wait for the `main` build to finish successfully. It must publish these packages before Argo CD deploys them:

```text
ghcr.io/<IMAGE_NAMESPACE>/idp-llm-gateway
ghcr.io/<IMAGE_NAMESPACE>/idp-model-serving
ghcr.io/<IMAGE_NAMESPACE>/idp-docs-assistant
ghcr.io/<IMAGE_NAMESPACE>/idp-aiops-agent
ghcr.io/<IMAGE_NAMESPACE>/idp-portal
```

The Kubernetes manifests do not configure a GHCR image-pull secret. For this guide, make each published GHCR package **public** in GitHub's package settings before deploying it. If your images must remain private, configure Kubernetes image pull credentials and update the manifests first.

## 7. Install Argo CD in EKS

These commands install Argo CD into the AWS EKS cluster selected in step 5:

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
kubectl -n argocd get pods
```

For this guide, the GitHub repository must be readable by Argo CD (for example, public). For a private repository, add a read-only repository credential to Argo CD before creating the root application.

## 8. Add optional application secrets

The LLM gateway is configured for mock mode by default. No provider API key is needed to start the platform.

To use a real Anthropic provider instead of mock responses, create the Kubernetes secret and change `LLM_PROVIDER` from `mock` to `anthropic` in the deployment manifest. Do not commit the API key or put it in a manifest. Run these commands from the repository root before bootstrapping Argo CD:

```bash
kubectl create namespace llm-gateway \
  --dry-run=client -o yaml | kubectl apply -f -

read -rsp "Anthropic API key: " ANTHROPIC_API_KEY
echo
printf '%s' "$ANTHROPIC_API_KEY" | \
  kubectl -n llm-gateway create secret generic llm-gateway-secrets \
    --from-file=ANTHROPIC_API_KEY=/dev/stdin \
    --dry-run=client -o yaml | kubectl apply -f -
unset ANTHROPIC_API_KEY

sed -i 's/value: "mock"/value: "anthropic"/' \
  gitops/manifests/llm-gateway/deployment.yaml
git add gitops/manifests/llm-gateway/deployment.yaml
git commit -m "config: enable Anthropic provider"
git push origin main
```

Wait for Jenkins to finish the resulting `main` build before bootstrapping Argo CD.

The portal's optional read-only workload/log features can use a generated access token. This token is only a shared access gate; it is not a replacement for user authentication. Keep the portal private or protect it with SSO before enabling these features:

```bash
export OPS_API_TOKEN="$(openssl rand -hex 32)"
kubectl create namespace portal \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n portal create secret generic platform-ops-access \
  --from-literal=token="$OPS_API_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -
unset OPS_API_TOKEN
```

Both secrets are optional for starting the application; do not enable real incident remediation without first reviewing and securing its Kubernetes permissions.

## 9. Start the applications with Argo CD

The root application points to `gitops/apps/`. Argo CD will discover the platform applications, including the monitoring chart and dashboard:

```bash
kubectl apply -f gitops/bootstrap/root.yaml

# Watch the Argo CD applications appear.
kubectl get applications -n argocd --watch
```

In another terminal, check the deployed workloads:

```bash
kubectl get pods --all-namespaces
kubectl get services --all-namespaces
```

Wait for the portal, four backend services, Prometheus, and Grafana pods to become `Running` and ready. Argo CD syncs repository changes automatically. You do not need to install a second copy of Prometheus/Grafana with Helm; the root application includes the monitoring application.

## 10. Open the portal and check the services

For a private cluster or a first test, use a temporary port-forward from your workstation. This connects to the AWS EKS service; the application itself is still running on AWS:

```bash
kubectl -n portal port-forward svc/portal 8501:8501
```

Open `http://localhost:8501` while that command is running. In another terminal, check the backend health endpoints:

Keep the port-forward running. From a second terminal, run the following checks inside each EKS pod:

```bash
for ns in docs-assistant model-serving llm-gateway aiops-agent; do
  pod="$(kubectl -n "$ns" get pods -l "app=$ns" \
    -o jsonpath='{.items[0].metadata.name}')"
  printf '%s: ' "$ns"
  kubectl -n "$ns" exec "$pod" -- \
    python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/healthz').read().decode())"
done
```

To open Grafana from your workstation, run this in a separate terminal and visit `http://localhost:3000`:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Grafana authentication is controlled by the Helm chart values and generated Kubernetes secrets. Do not assume a default password; follow the chart's secret/configuration for this deployment.

For a permanent web address, configure a supported AWS ingress/load-balancer controller, DNS, TLS, and authentication. The checked-in ingress uses the example hostname `idp.local`; it does not create a public AWS load balancer or secure public access by itself.

## 11. Make a change and deploy an update

Push a change to `main`:

```bash
git add path/to/changed-file
git commit -m "Describe your change"
git push origin main
```

Replace `path/to/changed-file` with the paths of the files you actually changed. Do not use `git add .` here: generated files, Terraform plans, or local configuration could be added accidentally. Jenkins tests the change, publishes new image tags to GHCR, and commits those tags to the GitOps manifests. Argo CD then sees the Git change and updates the AWS EKS workloads. Check the Jenkins build and Argo CD applications if an update does not appear.

## 12. Stop and remove AWS resources when finished

This removes the Kubernetes applications and destroys the AWS infrastructure, which can permanently delete data. First back up anything you need and check the AWS account, cluster, bucket, and Terraform state. The S3 bucket must be empty before Terraform can delete it.

```bash
# Remove the Argo CD root application and its managed workloads.
kubectl delete -f gitops/bootstrap/root.yaml

# If you intentionally want to delete every object in this dedicated artifact
# bucket, review the bucket name and contents before running this command.
aws s3 ls "s3://${ARTIFACT_BUCKET}"
aws s3 rm "s3://${ARTIFACT_BUCKET}" --recursive

# Destroy the Terraform-managed AWS infrastructure.
cd terraform/envs/dev
terraform destroy \
  -var="region=${AWS_REGION}" \
  -var="artifact_bucket=${ARTIFACT_BUCKET}"
```

Jenkins is managed separately and is not removed by `terraform destroy` in this project.
