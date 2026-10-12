terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # Use remote state for anything shared:
  # backend "s3" { bucket = "YOUR-TF-STATE" key = "idp/dev.tfstate" region = "ap-south-1" }
}

variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "artifact_bucket" {
  type        = string
  description = "Globally unique S3 bucket name"
}

provider "aws" { region = var.region }

module "network" {
  source = "../../modules/network"
  name   = "idp-dev"
  azs    = ["${var.region}a", "${var.region}b"]
}

module "cluster" {
  source     = "../../modules/cluster"
  name       = "idp-dev"
  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_subnets
}

module "storage" {
  source      = "../../modules/storage"
  bucket_name = var.artifact_bucket
}

output "cluster_name" { value = module.cluster.cluster_name }
output "kubeconfig_cmd" { value = "aws eks update-kubeconfig --name ${module.cluster.cluster_name} --region ${var.region}" }
