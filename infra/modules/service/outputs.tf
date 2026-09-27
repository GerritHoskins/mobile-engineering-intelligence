output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "ecr_repository_name" {
  value = aws_ecr_repository.this.name
}

output "ecr_repository_arn" {
  value = aws_ecr_repository.this.arn
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.this.family
}

output "service_security_group_id" {
  value = aws_security_group.service.id
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}

output "alb_arn_suffix" {
  value = aws_lb.this.arn_suffix
}

output "target_group_arn_suffix" {
  value = aws_lb_target_group.this.arn_suffix
}

output "cluster_arn" {
  value = aws_ecs_cluster.this.arn
}

output "image" {
  value = local.image
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}
