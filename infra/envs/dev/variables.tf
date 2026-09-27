variable "aws_account_id" {
  description = "The only AWS account this config may touch (guards against a wrong profile)."
  type        = string
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "allowed_cidrs" {
  description = "IPv4 CIDRs allowed through CloudFront (the API has no auth yet), e.g. your public IP as a /32."
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

variable "github_oidc_subject_prefix" {
  description = "GitHub OIDC sub prefix (immutable subject claims: owner/repo names plus IDs)."
  type        = string
  default     = "repo:GerritHoskins@39583066/mobile-engineering-intelligence@1368764452"
}

variable "existing_github_oidc_provider_arn" {
  description = "Set if the account already has a GitHub OIDC provider (only one is allowed)."
  type        = string
  default     = null
}

variable "alert_email" {
  description = "Receives alarm and ingestion-failure notifications."
  type        = string
}

variable "anthropic_aws_workspace_id" {
  description = "Claude Platform on AWS workspace ID (wrkspc_...), created in the AWS console. Not a secret."
  type        = string
  default     = null
}

variable "ingestion_schedule_enabled" {
  description = "Turn on once an image is deployed and the vendor secrets have values."
  type        = bool
  default     = false
}

variable "existing_network" {
  description = "Use an existing VPC instead of creating one. Its private subnets need a NAT route."
  type = object({
    vpc_id             = string
    public_subnet_ids  = list(string)
    private_subnet_ids = list(string)
  })
  default = null
}

variable "tags" {
  description = "Extra tags on every resource (e.g. an organisation's cost-centre or owner tags)."
  type        = map(string)
  default     = {}
}
