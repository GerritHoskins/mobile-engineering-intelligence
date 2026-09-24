output "state_bucket" {
  description = "Put this in infra/envs/dev/backend.hcl."
  value       = aws_s3_bucket.state.bucket
}
