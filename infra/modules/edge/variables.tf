variable "name" {
  type = string
}

variable "alb_dns_name" {
  type = string
}

variable "allowed_cidrs" {
  description = "IPv4 CIDRs allowed through CloudFront, e.g. your public IP as a /32."
  type        = list(string)
}

variable "origin_verify_header" {
  type    = string
  default = "X-Origin-Verify"
}

variable "origin_verify_secret" {
  type      = string
  sensitive = true
}
