output "url" {
  description = "The API, over HTTPS, reachable from allowed_cidrs only."
  value       = module.edge.url
}

output "ecr_repository_name" {
  description = "GitHub repo variable ECR_REPOSITORY."
  value       = module.service.ecr_repository_name
}

output "github_role_arn" {
  description = "GitHub repo variable AWS_ROLE_ARN."
  value       = module.github_oidc.role_arn
}

output "cluster_name" {
  value = module.service.cluster_name
}

output "service_name" {
  value = module.service.service_name
}

output "jobs_task_definition_family" {
  description = "For one-off jobs: aws ecs run-task --task-definition <this> (override the command to seed)."
  value       = module.jobs.task_definition_family
}

output "log_group_name" {
  value = module.service.log_group_name
}

output "run_task_network_configuration" {
  description = "For one-off tasks via aws ecs run-task --network-configuration."
  value = format(
    "awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=DISABLED}",
    join(",", local.network.private_subnet_ids),
    module.service.service_security_group_id,
  )
}

output "vendor_secret_names" {
  description = "Fill each with: aws secretsmanager put-secret-value --secret-id <name> --secret-string ..."
  value       = module.secrets.names
}

output "dashboard_name" {
  value = module.observability.dashboard_name
}
