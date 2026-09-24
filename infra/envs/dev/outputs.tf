output "alb_url" {
  value = "http://${module.service.alb_dns_name}"
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

output "task_definition_family" {
  value = module.service.task_definition_family
}

output "log_group_name" {
  value = module.service.log_group_name
}

output "run_task_network_configuration" {
  description = "For one-off tasks (e.g. seeding) via aws ecs run-task --network-configuration."
  value = format(
    "awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=ENABLED}",
    join(",", module.network.public_subnet_ids),
    module.service.service_security_group_id,
  )
}
