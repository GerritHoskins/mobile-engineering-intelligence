variable "name" {
  type = string
}

variable "subject_prefix" {
  description = <<-EOT
    Prefix of the GitHub OIDC `sub` claim, before ":ref:...". Repositories with
    immutable subject claims use "repo:<owner>@<owner_id>/<repo>@<repo_id>";
    check with: gh api repos/<owner>/<repo>/actions/oidc/customization/sub
  EOT
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
