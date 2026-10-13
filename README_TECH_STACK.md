# Project Technology Stack: What It Is and Why It Is Used

This guide explains the main technologies in this project in simple English. For each one, it describes what the technology is, what it does here, and why it was chosen.

## The project in one sentence

This project is a developer portal made from several small web services. Jenkins checks and packages code, GitHub stores the code and deployment instructions, and Argo CD keeps the application running on AWS EKS.

## 1. Languages and application framework

### Python

**What it is:** A programming language often used for web services, automation, and data science.

**How this project uses it:** The portal backend and the four application services are written in Python.

**Why it is used:** Python has clear syntax and useful libraries for web APIs, machine learning, and Kubernetes automation. This makes it a practical choice for connecting the portal, AI-related examples, and operations features.

### FastAPI

**What it is:** A Python framework for building web APIs. An API lets one program ask another program to do something.

**How this project uses it:** It powers the portal backend and the `docs-assistant`, `model-serving`, `llm-gateway`, and `aiops-agent` services.

**Why it is used:** FastAPI makes it straightforward to define request and response endpoints. It also creates interactive API documentation, which helps developers test the services.

### Uvicorn

**What it is:** A server that runs Python web applications.

**How this project uses it:** Each FastAPI service starts with Uvicorn inside its container.

**Why it is used:** FastAPI defines what the application should do; Uvicorn listens for network requests and passes them to FastAPI.

### Pydantic

**What it is:** A Python library for describing and checking the shape of data.

**How this project uses it:** API request and response models describe fields such as documentation questions, risk inputs, and chat prompts.

**Why it is used:** Checking incoming data helps reject requests that are incomplete or have the wrong format before the service processes them.

### HTTPX

**What it is:** A Python library for sending HTTP requests to other services.

**How this project uses it:** The portal calls the backend services. The docs assistant and AIOps agent also call the LLM gateway or Prometheus.

**Why it is used:** The system is split into separate services, so they need a way to communicate over the network. HTTPX supports asynchronous requests, which fits FastAPI's request handling.

## 2. Browser interface

### HTML, CSS, and JavaScript

**What they are:** The basic web technologies used to build pages, style them, and make them interactive.

**How this project uses them:** They make the Forge Console that appears in a web browser.

**Why they are used:** They run in the browser without needing a separate desktop application.

### Three.js

**What it is:** A JavaScript library for drawing interactive 3D graphics in a web browser.

**How this project uses it:** It renders the interactive 3D view of the platform's services.

**Why it is used:** The 3D map gives users a visual way to explore the system and see its main parts. It is a visualization; it does not run or manage the services.

### Vite

**What it is:** A tool for developing and building browser applications.

**How this project uses it:** Jenkins runs Vite to turn the portal's JavaScript, HTML, and CSS into production-ready browser files. The portal Docker image also builds these files.

**Why it is used:** The browser needs optimized, ready-to-serve files. Vite handles that build step.

**Important:** The project uses JavaScript and Three.js directly; it does not use React.

## 3. The five application services

Each service has one main job. Keeping jobs separate makes it easier to understand, test, and package each part.

### Portal (Forge Console)

**What it does:** Provides the website engineers use to access platform features. Its FastAPI backend serves the page and sends requests to the correct internal service.

**Why it is separate:** The browser should have one clear entry point rather than needing direct access to every internal service.

### `docs-assistant`

**What it does:** Searches the included Markdown documentation for useful sections and sends the relevant context to the LLM gateway.

**Technology:** TF-IDF and cosine similarity from scikit-learn.

**In simple terms:** TF-IDF gives words more weight when they help distinguish one document from another. Cosine similarity compares the question with the documents and finds the closest matches.

**Why it is used:** It demonstrates document search without requiring a separate vector database or a paid embedding service.

**Limit:** This is keyword-based retrieval, not a modern embedding-based search system. The quality depends on the words in the question and the available documents.

### `model-serving`

**What it does:** Accepts release-related inputs and returns a low, medium, or high deployment-risk estimate.

**Technology:** A scikit-learn logistic-regression model, with input scaling.

**Why it is used:** It demonstrates how a model can be exposed as a web API and called by the portal.

**Limit:** The model is trained on synthetic example data. It is for demonstrating the workflow, not for making real production release decisions.

### `llm-gateway`

**What it does:** Gives other services one shared place to send language-model requests. It can cache responses and track estimated tokens, latency, and cost.

**Why it is used:** A shared gateway keeps provider calls and usage tracking in one place instead of repeating that logic in every service.

**Default behavior:** The Kubernetes deployment uses a mock provider by default, so it can respond without an external model API key.

**Optional behavior:** It can call Anthropic when configured with the provider setting and a secret API key.

**Limit:** Displayed provider costs are estimates using configured prices. They are not billing data from an AI provider.

### `aiops-agent`

**What it does:** Checks Prometheus measurements, records incidents, and can summarize information through the LLM gateway. It has an allowlisted restart feature for Kubernetes workloads.

**Why it is used:** It demonstrates how monitoring, incident context, and operations actions can be connected.

**Safety note:** Automatic remediation is disabled by default. Enabling restarts requires careful review of access permissions and operational safeguards.

## 4. Packaging and running the application

### Docker

**What it is:** A tool for packaging an application and its required files into an image.

**How this project uses it:** Each application service has a Dockerfile. Jenkins builds five images from the repository.

**Why it is used:** The same packaged service can run in a developer environment or in Kubernetes without manually installing all its Python dependencies on the destination machine.

### Docker Compose

**What it is:** A tool for running several Docker containers together from one configuration file.

**How this project uses it:** `docker-compose.yml` can start a local version of the platform for development.

**Why it is used:** It is convenient for trying the services on a workstation.

**Important:** Docker Compose is an optional local-development path. The target hosted environment for this project is AWS EKS.

### Kubernetes

**What it is:** A system for running and managing containers across a group of machines.

**How this project uses it:** Kubernetes Deployments describe the running application containers. Services provide network names for communication, and health probes check whether containers respond.

**Why it is used:** It can restart failed containers and helps manage multiple services as a coordinated application.

### Amazon EKS

**What it is:** Amazon's managed Kubernetes service.

**How this project uses it:** It is the AWS environment intended to run the portal, four backend services, Prometheus, and Grafana.

**Why it is used:** AWS manages the Kubernetes control plane, while the project's worker nodes run the containers.

**Important:** EKS, EC2 worker nodes, networking, and NAT can cost money while running. Review AWS costs and remove resources when they are no longer needed.

## 5. Cloud infrastructure

### AWS VPC and subnets

**What they are:** A VPC is a private network in AWS. Subnets divide that network into smaller sections.

**How this project uses them:** Terraform creates a VPC with public and private subnets. EKS worker nodes are placed in private subnets.

**Why they are used:** They provide network boundaries and a place for the cluster and its workers to run.

### EC2 worker nodes

**What they are:** Virtual machines provided by Amazon EC2.

**How this project uses them:** EKS's managed node group uses EC2 instances to run application containers. The current Terraform default is two `t3.large` nodes, with a minimum of one and maximum of four.

**Why they are used:** Kubernetes needs worker machines to run the containers. AWS EKS does not mean that application containers run without compute resources.

### NAT gateway

**What it is:** An AWS network component that lets resources in private subnets make outbound connections without accepting direct inbound internet connections.

**How this project uses it:** Terraform enables a single NAT gateway for the private subnets.

**Why it is used:** Private EKS workers may need outbound access to download container images or packages.

**Cost note:** NAT gateways have ongoing AWS charges. The configuration uses one shared gateway as a cost-saving choice, not a high-availability design.

### Amazon S3

**What it is:** AWS object storage for files and other data.

**How this project uses it:** Terraform creates a versioned, encrypted, private bucket for platform artifacts.

**Limit:** The current application does not yet upload its normal runtime data to this bucket. Creating the bucket does not automatically connect it to the services.

### Terraform

**What it is:** A tool for describing cloud infrastructure in configuration files and creating it in a repeatable way.

**How this project uses it:** Terraform uses the AWS provider and community VPC/EKS modules to create the AWS network, EKS cluster, worker node group, and S3 bucket.

**Why it is used:** Instead of creating the infrastructure by clicking through the AWS console, the project keeps the requested setup in version-controlled files.

**Limit:** Terraform provisions infrastructure. It does not install or update the application services inside Kubernetes; Argo CD does that. Jenkins hosting is also managed separately.

## 6. CI/CD and GitOps

### Git and GitHub

**What they are:** Git tracks changes to files; GitHub hosts Git repositories and lets people collaborate on them.

**How this project uses them:** The repository contains source code, Dockerfiles, Terraform, and Kubernetes deployment instructions. Jenkins pushes updated image tags back to the same repository.

**Why they are used:** The code and the desired deployment configuration have a shared, reviewable history.

### Jenkins

**What it is:** A server that runs automated jobs when code changes.

**How this project uses it:** The Jenkinsfile runs tests and builds the portal on branches and pull requests. On `main`, it builds five service images, pushes them to GHCR, runs a Trivy scan, updates image tags in Git, and pushes the tag update.

**Why it is used:** It automates the repeated steps needed to check and package changes.

**Limit:** Jenkins does not create the AWS infrastructure or directly deploy the application to EKS in this project. It is installed and configured separately from the Terraform code.

### GHCR (GitHub Container Registry)

**What it is:** GitHub's service for storing container images.

**How this project uses it:** Jenkins pushes the five versioned service images here. EKS worker nodes download the image versions named in the Kubernetes manifests.

**Why it is used:** It stores the built packages in a place Jenkins can publish to and the cluster can retrieve from.

### Trivy

**What it is:** A tool that scans container images and other project files for known security issues.

**How this project uses it:** Jenkins scans each image for critical vulnerabilities.

**Important:** The current pipeline is report-only (`--exit-code 0`). It reports findings but does not fail the build because of them.

### GitOps

**What it is:** A way of managing deployments by keeping the desired configuration in Git.

**How this project uses it:** The Kubernetes manifests in `gitops/` say what images and settings should run in the cluster.

**Why it is used:** Changes to deployment settings can be reviewed and tracked like changes to application code.

### Argo CD

**What it is:** A deployment tool that watches Git repositories and applies Kubernetes configuration.

**How this project uses it:** Argo CD reads the applications under `gitops/apps/` and syncs their manifests to AWS EKS.

**Why it is used:** Jenkins can publish a new image and update Git, then Argo CD notices the desired change and brings the cluster into line with it.

**Simple difference:** Jenkins checks and packages code. Argo CD applies the declared application configuration to Kubernetes.

### Kustomize

**What it is:** A Kubernetes configuration tool for organizing and adjusting YAML manifests.

**How this project uses it:** Each service's `kustomization.yaml` names the container image and tag to deploy.

**Why it is used:** Jenkins can update the image tag in one clear place while the deployment YAML describes the rest of the service configuration.

## 7. Monitoring and dashboards

### Prometheus

**What it is:** A monitoring system that collects time-based measurements called metrics.

**How this project uses it:** It scrapes metrics from the four backend services. The AIOps agent can query Prometheus to check its incident rules.

**Why it is used:** It gives the services a shared way to publish and inspect measurements such as request counts, errors, and latency.

### Grafana

**What it is:** A dashboard tool that can display data from systems such as Prometheus.

**How this project uses it:** It displays the Mission Control dashboard for service and platform measurements.

**Why it is used:** A visual dashboard is easier to inspect than raw metrics by themselves.

### Helm

**What it is:** A package manager for Kubernetes applications.

**How this project uses it:** The monitoring GitOps application installs the `kube-prometheus-stack` Helm chart, which supplies Prometheus and Grafana.

**Why it is used:** A maintained chart installs a group of monitoring components together with their Kubernetes configuration.

## 8. Testing

### Pytest

**What it is:** A framework for running automated Python tests.

**How this project uses it:** Jenkins runs the test suite in `tests/` before it publishes images.

**Why it is used:** It can catch common application problems before a change is packaged.

### Node.js and npm

**What they are:** Node.js runs JavaScript tools outside the browser; npm installs JavaScript packages.

**How this project uses them:** Jenkins uses Node.js 22 and npm to install the portal's build tools and run its Vite build.

**Why they are used:** They provide the tooling needed to prepare the browser files before the portal image is built.

## 9. Why use many smaller pieces?

Each part has a clear responsibility:

1. **Terraform** creates AWS infrastructure.
2. **Jenkins** tests changes and packages application images.
3. **GHCR** stores those images.
4. **GitHub** stores the application code and desired image versions.
5. **Argo CD** applies the desired state to EKS.
6. **Kubernetes/EKS** runs and checks the services.
7. **Prometheus and Grafana** collect and show system measurements.
8. **The portal and backend APIs** provide the developer-facing features.

Separating these responsibilities makes the project easier to understand and change. It also means that each part needs to be configured and connected correctly; adding a tool to the repository does not automatically create or secure its cloud service.

## 10. Important project limits

- The deployment-risk model uses synthetic training data. Do not use it to approve real releases.
- The documentation search uses TF-IDF keyword matching, not embeddings or a vector database.
- The LLM gateway uses mock responses by default. A real provider requires configuration and a secret API key.
- LLM usage costs are estimates, not values read from a provider bill.
- Trivy scanning reports critical findings but does not block the current pipeline.
- AIOps remediation is disabled by default.
- The S3 artifact bucket is provisioned but is not yet used by the normal application flow.
- Jenkins, public image/repository access, secure ingress, DNS, TLS, and user authentication require separate setup.
- Terraform state currently uses a local backend. Shared use needs a protected remote backend and state locking.

## Related guides

- [Main project README](README.md)
- [Simple-English architecture diagram guide](README_DIAGRAM.md)
- [Step-by-step AWS deployment guide](README_AWS_DEPLOYMENT.md)
