variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "org" {
  description = "config/org.<name>.yaml to ingest."
  type        = string
  default     = "demo"
}

variable "ingest_days" {
  description = "Sentry lookback window per run."
  type        = number
  default     = 14
}

variable "schedule_expression" {
  type    = string
  default = "rate(6 hours)"
}

variable "schedule_enabled" {
  description = "False until an image exists and the vendor secrets are filled in."
  type        = bool
  default     = false
}

variable "image" {
  type = string
}

variable "cluster_arn" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  description = "The service security group: RDS admits it, egress goes through the NAT."
  type        = string
}

variable "log_group_name" {
  type = string
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
  type = string
}

variable "vendor_secret_arns" {
  description = "Environment variable name -> Secrets Manager ARN."
  type        = map(string)
}
