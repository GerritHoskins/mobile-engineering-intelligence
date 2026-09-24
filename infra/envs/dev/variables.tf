variable "aws_account_id" {
  description = "The only AWS account this config may touch (guards against a wrong profile)."
  type        = string
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to reach the ALB, e.g. your public IP as a /32."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && !contains(var.allowed_cidrs, "0.0.0.0/0")
    error_message = "Set at least one CIDR, and don't open the ALB to 0.0.0.0/0."
  }
}

variable "image_tag" {
  description = "ECR image tag (git SHA) to run. Leave empty for the first apply, before any image exists."
  type        = string
  default     = ""
}

variable "github_repository" {
  type    = string
  default = "GerritHoskins/mobile-engineering-intelligence"
}

variable "existing_github_oidc_provider_arn" {
  description = "Set if the account already has a GitHub OIDC provider (only one is allowed)."
  type        = string
  default     = null
}
