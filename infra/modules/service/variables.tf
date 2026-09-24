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
  type = list(string)
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to reach the ALB on port 80."
  type        = list(string)
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

variable "cpu" {
  type    = number
  default = 256
}

variable "memory" {
  type    = number
  default = 512
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
