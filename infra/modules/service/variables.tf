variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  description = "Subnets for the ALB."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Subnets for the tasks (egress through a NAT)."
  type        = list(string)
}

variable "origin_verify_header" {
  description = "Header CloudFront adds to every origin request; the ALB forwards only requests carrying it."
  type        = string
  default     = "X-Origin-Verify"
}

variable "origin_verify_secret" {
  description = "Value of the origin-verify header."
  type        = string
  sensitive   = true
}

variable "anthropic_aws_workspace_id" {
  description = "Claude Platform on AWS workspace (wrkspc_...). Null leaves the LLM endpoints unconfigured."
  type        = string
  default     = null
}

variable "adot_version" {
  description = "AWS Distro for OpenTelemetry collector image tag."
  type        = string
  default     = "v0.50.0"
}

variable "image_tag" {
  description = "ECR image tag to run. Empty means no task runs yet (desired_count 0)."
  type        = string
  default     = ""
}

variable "container_port" {
  type    = number
  default = 8000
}

# The API plus the ADOT sidecar.
variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "db_host" {
  type = string
}

variable "db_port" {
  type = number
}

variable "db_name" {
  type = string
}

variable "db_secret_arn" {
  description = "RDS-managed master user secret (JSON with username/password)."
  type        = string
}

variable "db_security_group_id" {
  type = string
}
