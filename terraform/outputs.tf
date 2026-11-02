output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_region" {
  description = "AWS region containing the EKS cluster."
  value       = var.aws_region
}

output "ecr_repository_urls" {
  description = "Immutable ECR repository URLs for application services."
  value       = { for name, repo in aws_ecr_repository.service : name => repo.repository_url }
}
