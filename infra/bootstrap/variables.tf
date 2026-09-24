variable "aws_account_id" {
  description = "The only AWS account this config may touch (guards against a wrong profile)."
  type        = string
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "budget_email" {
  description = "Where budget alerts are sent."
  type        = string
}

variable "monthly_budget_usd" {
  type    = string
  default = "10"
}
