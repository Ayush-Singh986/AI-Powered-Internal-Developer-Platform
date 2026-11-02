variable "aws_region" {
  description = "AWS region for the demo platform."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short prefix for AWS resources."
  type        = string
  default     = "aiops-demo"
}

variable "environment" {
  description = "Environment name used in resource tags."
  type        = string
  default     = "demo"
}

variable "cluster_version" {
  description = "EKS Kubernetes version supported by the selected AWS region."
  type        = string
  default     = "1.35"
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "Public client CIDRs permitted to reach the EKS Kubernetes API endpoint."
  type        = list(string)
}

variable "vpc_cidr" {
  description = "CIDR range for the EKS VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "node_instance_types" {
  description = "EC2 instance types for the private EKS node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "monthly_budget_limit" {
  description = "Monthly AWS cost threshold in USD for the budget alert."
  type        = number
  default     = 200
  validation {
    condition     = var.monthly_budget_limit > 0
    error_message = "monthly_budget_limit must be greater than zero."
  }
}

variable "budget_alert_email" {
  description = "Email address that receives AWS monthly budget alerts."
  type        = string
  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_alert_email))
    error_message = "budget_alert_email must be a valid email address."
  }
}
