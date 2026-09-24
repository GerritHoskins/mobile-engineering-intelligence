variable "name" {
  type = string
}

variable "repository" {
  description = "GitHub repository as owner/name."
  type        = string
}

variable "ecr_repository_arn" {
  type = string
}

variable "existing_provider_arn" {
  description = "ARN of an existing GitHub OIDC provider in the account, if any."
  type        = string
  default     = null
}
