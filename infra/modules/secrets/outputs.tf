output "env_to_arn" {
  description = "Environment variable name -> secret ARN, for ECS task definition secrets."
  value       = { for env, secret in aws_secretsmanager_secret.vendor : env => secret.arn }
}

output "names" {
  description = "Secret names, for aws secretsmanager put-secret-value --secret-id."
  value       = { for env, secret in aws_secretsmanager_secret.vendor : env => secret.name }
}
