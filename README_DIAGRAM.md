# The Architecture Diagram, in Simple English

This guide explains the [Interactive Mermaid Diagram](README.md#interactive-mermaid-diagram) in easy language. The project is intended to run on **AWS EKS**. Docker Compose and `kind` are only optional tools for local development.

## The main idea

Think of the project as two parts:

1. **Getting new code ready and updating the AWS deployment.**
2. **Running the platform services on AWS and letting them work together.**

The diagram shows both parts.

## Part 1: How new code reaches AWS

1. **A developer pushes code to GitHub.** The GitHub repository contains the application code and the Kubernetes deployment instructions.
2. **Jenkins starts a build.** GitHub tells Jenkins that code changed. Jenkins runs the tests and builds the website files.
3. **Jenkins creates the service images.** An image is a packaged version of a service that Kubernetes can run. Jenkins pushes these images to **GHCR**, GitHub's container-image storage.
4. **Jenkins checks the images.** Trivy looks for critical security problems. This check reports what it finds, but does not stop the pipeline.
5. **Jenkins updates the deployment instructions.** It writes the new image version into the GitHub repository. The image and the instruction that names that image are separate things.
6. **Argo CD notices the change.** Argo CD checks GitHub regularly (about every three minutes), reads the deployment instructions, and applies them to the AWS EKS cluster.
7. **AWS EKS starts the services.** The EKS worker machines download the images from GHCR and run them.

Jenkins prepares and publishes the new versions. Argo CD applies the deployment instructions. They do different jobs.

## Part 2: What runs inside AWS EKS

The large box in the diagram is the AWS EKS cluster. It contains the platform services:

- **Portal (Forge Console):** The website engineers use to reach the platform features.
- **docs-assistant:** Searches the project's documents and runbooks for useful information.
- **model-serving:** Estimates deployment risk using the project's demo model.
- **llm-gateway:** Provides one shared route for language-model requests and tracks estimated usage and cost.
- **aiops-agent:** Watches service information and can create incidents. Restarting a service is disabled by default.
- **Prometheus:** Collects measurements, called metrics, from the four backend services.
- **Grafana:** Shows those measurements on dashboards.

The diagram's `/ask`, `/predict`, `/v1/chat`, and `/incidents` labels are the kinds of requests the portal sends to the services. In simple terms: the portal asks the right service to do each job.

The docs assistant and AIOps agent can also ask the LLM gateway for help. The AIOps agent asks Prometheus for measurements. Prometheus sends those measurements to Grafana, and the portal can show the Grafana dashboard.

The `:8000`, `:8501`, `:9090`, and `:3000` numbers are network ports used by these services. They are not, by themselves, public website addresses.

## What Terraform does

Terraform creates the AWS foundation shown under the cluster: the network (VPC), the EKS cluster, and an S3 bucket for artifacts. Argo CD then installs and updates the platform applications inside EKS.

Terraform does **not** create the Jenkins server in this project. Jenkins must already be running and configured separately.

## Follow the arrows at a glance

- **Developer → GitHub → Jenkins:** send code and start checks.
- **Jenkins → GHCR:** store the packaged service images.
- **Jenkins → GitHub:** record which image versions should be deployed.
- **GitHub → Argo CD → AWS EKS:** read and apply the deployment instructions.
- **Portal → platform services:** send feature requests.
- **Services → Prometheus → Grafana:** collect and display service measurements.
- **Terraform → AWS EKS:** create the AWS infrastructure for the applications.

## One important note

This diagram explains the intended AWS deployment, but it does not mean every AWS resource is automatically ready just because the code is in GitHub. AWS access, Jenkins, GHCR credentials, Argo CD, and any public web address or secure ingress must be configured for your environment.
