# The Project, From Beginning to End

This guide explains the AI-Powered Internal Developer Platform in simple English. It follows the project from the moment a developer starts it, through the work the platform can do, and then through the process used to test and deploy it.

## What the project is for

An internal developer platform, or IDP, brings common engineering tools together in one place. In this project, that place is the Forge Console. An engineer can use it to check whether services are healthy, search runbooks, ask an AI model a question, estimate the risk of a code change, review incidents, and make an example infrastructure cost estimate.

The project is made of several small services rather than one large application. Each service has a focused job, and the portal sends requests to the service responsible for that job. The project is designed to run in AWS on Kubernetes using Amazon EKS. Docker Compose is also provided so a developer can run a local demonstration without first creating an AWS cluster.

## Starting the project on a developer's computer

The quickest way to see the platform is to install Docker Desktop with Docker Compose, open a terminal in the project folder, and run:

```text
docker compose up --build
```

Docker Compose builds the application images from the Dockerfiles in `services/`, creates a private network for them, and starts the services in the order their health checks require. The language-model gateway uses its mock provider by default, so the local setup does not need an external AI key. The main console appears at `http://localhost:8501`. Grafana is available at `http://localhost:3000`, Prometheus at `http://localhost:9090`, and the individual service APIs are also exposed on the local ports configured in `docker-compose.yml`.

When the developer is finished, `docker compose down` stops the containers. The named Prometheus and Grafana data volumes remain unless the developer explicitly removes them with `docker compose down -v`.

## What happens when someone opens the console

The portal is the front door to the platform. Its server is a FastAPI application in `services/portal/app.py`. The browser interface is built from the source in `services/portal/web/` using Vite, with Three.js used for the interactive platform view. The portal serves that built interface and provides its own API for the browser.

When the page loads, the browser asks the portal which environments are configured and then requests an overview. The portal checks the health endpoint of each configured service and reports whether it is responding. Development is configured by default for the local Compose setup. Staging and Production are shown as unconfigured until their service addresses are supplied through the environment configuration. This avoids pretending that a service is healthy when no real address has been set.

The portal usually does not perform the specialist work itself. It forwards a request to the correct service, receives the result, and shows that result in the console. That separation lets each service be changed or scaled without turning the portal into one large application.

## How the platform answers documentation questions

The documentation assistant reads the Markdown documents in `services/docs-assistant/docs/` when it starts. These include example runbooks and operational guidance. It splits the documents into sections and builds a simple TF-IDF search index, which helps it find sections containing words related to a question.

When an engineer asks a question, the portal sends it to the documentation assistant. The assistant finds up to three matching sections and sends the question together with those sections to the language-model gateway. If the gateway responds, the assistant returns the answer and identifies the documents used. If no useful section is found, it says so. If the gateway is unavailable, it returns a short extract from the best matching section instead of making the whole documentation feature unavailable.

This is a small demonstration of retrieval-augmented generation, often shortened to RAG: first retrieve relevant written information, then use it as context for an answer.

## How the shared language-model gateway works

The LLM gateway is the common route for language-model requests. The portal, documentation assistant, and AIOps agent can all use it rather than each connecting directly to a model provider.

In local mode, the gateway returns a mock response and needs no API key. If it is configured to use Anthropic, it sends the request to Anthropic using the configured API key. It also keeps a small in-memory cache, so repeated equivalent prompts can be answered without another provider call. For requests it processes, it records estimated token use, latency, and cost metrics. The cost rates are configurable placeholders, so the estimate should not be treated as an actual provider invoice.

## How deployment risk is demonstrated

When an engineer submits release information in the console, the portal forwards it to `model-serving`. The service accepts values such as how many files and lines changed, test coverage, the time of day, and recent failures. It then returns a risk score, a low, medium, or high label, and a model version.

The current model is trained when needed using generated synthetic data and is saved to a temporary model file. This demonstrates how a prediction service can be called and monitored; it does not measure real production release outcomes. Its score should therefore be treated as an example, not as a reliable approval or deployment decision.

## How incidents and monitoring fit together

The backend services expose health checks and Prometheus metrics. The shared observability helper in `services/common/observability.py` provides the health and metrics endpoints to services that use it. The local Prometheus configuration scrapes service metrics, and Grafana reads those measurements to display the Mission Control dashboard.

The AIOps agent periodically asks Prometheus about configured error-rate and response-latency measurements. If a measurement crosses its rule's threshold, the agent creates an incident entry. It can also ask the LLM gateway for a short incident summary, and it falls back to a plain summary if the gateway cannot be reached. Incident entries are held in memory, so they are not a durable incident history and can disappear when the service restarts.

Remediation is disabled by default, including in the local Compose setup. In that mode, the agent records a dry-run action rather than restarting a service. Kubernetes restart behavior is an optional configuration and applies only to the named workloads in the agent's configuration. It should be reviewed and tested before being enabled in a real cluster.

The portal can also show workload inventory and logs when the optional operations access is configured. Local Docker access uses an optional read-only Docker socket proxy. In Kubernetes, the portal uses its service account and scoped permissions to read selected workloads. These operations are token-gated in the demonstration, but that token is not a replacement for proper user authentication or single sign-on.

## What the cost planner and reports do

The cost planner takes assumptions such as worker count, storage, networking, replicas, and container resources, then calculates an illustrative monthly and annual estimate. It uses fixed example prices in the portal code. It does not connect to AWS billing, fetch live prices, or know the discounts on a real account.

The report feature gathers a point-in-time service-health view, an incident count, the selected cost estimate, and the chosen environment. It is useful as a demonstration snapshot, but it is not a billing statement, a compliance record, or a durable operational archive.

## How a code change reaches AWS

Running locally shows the application, but AWS deployment follows a separate delivery path. A developer pushes a code change to GitHub. Jenkins checks out the code, runs the Python test suite, installs the portal's JavaScript dependencies, and builds the browser assets. These checks run before images are published.

For a normal build on the `main` branch, Jenkins builds container images for the portal and the four backend services. It tags each image with the commit identifier, pushes the images to GitHub Container Registry, and runs Trivy image scans. The current Jenkins pipeline reports critical findings but does not fail the build solely because of them.

Jenkins then updates the image names and tags in the Kubernetes manifests and pushes that deployment change back to GitHub. The `[skip ci]` marker on that generated deployment commit prevents the pipeline from needlessly repeating the same image-building process.

Argo CD has a different job from Jenkins. It watches the deployment configuration in Git and applies the desired configuration to Kubernetes. The root application in `gitops/bootstrap/root.yaml` points Argo CD at the application definitions in `gitops/apps/`. Those definitions point to the individual manifests under `gitops/manifests/`. When Git records a new image tag, Argo CD synchronizes the matching Kubernetes application, and the cluster pulls and runs that image.

## What Terraform creates

Terraform describes the AWS foundation in `terraform/`. The development environment connects three modules: the network module creates a VPC and its subnets, the cluster module creates an EKS cluster and its worker nodes, and the storage module creates a versioned, encrypted S3 bucket for artifacts.

Terraform creates the infrastructure, not the application services or the Jenkins server. Argo CD manages the Kubernetes applications after the cluster exists. AWS credentials, required cloud permissions, Jenkins, registry credentials, and the initial Argo CD installation must be arranged for the target environment. Creating an EKS cluster and its supporting network can also incur AWS charges, so the Terraform plan should be reviewed before it is applied.

## How to check the project

The tests in `tests/` exercise the main service behaviors and the portal API. They check, among other things, that gateway caching works, that model inputs produce sensible example risk ordering, that the documentation assistant can fall back when the gateway is offline, that AIOps respects dry-run and cooldown behavior, and that the portal validates operations access and cost-estimate inputs.

The test suite can be run from the project folder with:

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

The Jenkins pipeline runs the tests as part of its build. The Makefile also provides shortcuts for local Compose actions, tests, linting, Terraform commands, and bootstrapping a local kind cluster with Argo CD.

## Where the main project parts live

The service code is under `services/`. The portal has both a FastAPI server and a separate browser application, while the documentation assistant, model-serving service, LLM gateway, and AIOps agent each have their own application code and Dockerfile. Shared metrics and health-check code lives in `services/common/`.

The local multi-service setup is described in `docker-compose.yml`, and local Prometheus and Grafana configuration is under `deploy/local/`. Kubernetes application definitions are in `gitops/apps/`, while the detailed Deployments, Services, permissions, and monitoring configuration are in `gitops/manifests/`. AWS infrastructure code is under `terraform/`, and automated behavior tests are under `tests/`.

The other README files focus on specific topics: `README.md` introduces the project, `README_AWS_DEPLOYMENT.md` describes AWS deployment, `README_DIAGRAM.md` explains the architecture diagram, `README_TECH_STACK.md` describes the technologies, and `README_INTERVIEW.md` provides interview-oriented material.

## The whole story in one pass

A developer starts the platform locally or opens the deployed Forge Console. The portal checks configured services and forwards each task to the service that owns it. The documentation assistant searches written guidance, the model-serving service demonstrates a release-risk prediction, the LLM gateway centralizes language-model calls, and the AIOps agent watches metrics and records incidents. Prometheus gathers runtime measurements, and Grafana presents them. Separately, Jenkins tests and packages code, Git stores the image versions Kubernetes should run, Argo CD synchronizes that desired state, and Terraform supplies the AWS infrastructure underneath it.

This project is a learning and demonstration platform rather than a production-ready control plane. Before using it with real teams, replace synthetic training data and illustrative prices, configure secure identity and secret handling, review network and Kubernetes permissions, make incident data durable if required, and test deployment rollback and any automated remediation.

## Technical words in simple English

**IDP** means Internal Developer Platform. It is a collection of tools that helps engineers do common development and operations work from one place.

**TF-IDF** means “Term Frequency–Inverse Document Frequency.” It is a way for a search system to compare words in a question with words in documents. A word that appears often in a particular document, but not in every document, can help identify which document is most relevant. In this project, TF-IDF helps the documentation assistant find runbook sections related to a question.

**RAG** means Retrieval-Augmented Generation. The system first retrieves relevant written information, then gives that information to a language model to help it form an answer.

**LLM** means Large Language Model. It is an AI system that can understand and generate text. The project sends requests to an LLM through its shared gateway.

**API** means Application Programming Interface. It is a defined way for one piece of software to ask another piece of software to do something or return information.

**FastAPI** is the Python framework used to build the services' web APIs. **Vite** is a tool that builds and serves the portal's browser application. **Three.js** is a JavaScript library used to display interactive 3D graphics.

**Docker** packages an application and the things it needs into an image that can run as a container. **Docker Compose** runs several related containers together on one computer, which is how the local demonstration is started.

**Kubernetes** is a system for running and managing containers across machines. **EKS** means Amazon Elastic Kubernetes Service; it is AWS's managed Kubernetes service. A **cluster** is the group of machines and control components that run Kubernetes applications.

**CI/CD** means Continuous Integration and Continuous Delivery or Deployment. It describes automated steps that check code, package it, and help deliver it to an environment. In this project, Jenkins performs the build and publishing steps.

**Jenkins** is the automation server that runs the project's tests, builds its images, and publishes them. **GHCR** means GitHub Container Registry, where the built container images are stored.

**GitOps** is an approach where Git stores the desired deployment configuration and an automated tool applies that configuration to the running system. **Argo CD** is the tool in this project that watches the Git configuration and synchronizes it with Kubernetes.

**Terraform** is a tool for describing and creating infrastructure, such as networks, clusters, and storage, using configuration files. **VPC** means Virtual Private Cloud, a logically separated network in AWS. **S3** means Amazon Simple Storage Service, which stores files and other data as objects.

**Prometheus** collects and stores measurements about running services. These measurements are called **metrics**. **Grafana** displays metrics in dashboards so people can understand what is happening.

**A container image** is the packaged template used to start a container. A **container** is a running copy of an image. A **manifest** is a configuration file describing resources Kubernetes should create, such as an application deployment or network service.

**A cache** temporarily keeps a result so the same work does not have to be repeated. A **token** is a small piece of text processed by a language model; token counts help estimate model usage. **Synthetic data** is artificially generated example data, rather than information collected from real production activity.

**A health check** is a small request used to see whether a service is responding. **Latency** is the time a service takes to respond. **Remediation** means taking action to address a problem; in this project, an optional remediation can restart a supported Kubernetes deployment.
