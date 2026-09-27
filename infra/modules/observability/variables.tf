variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "account_id" {
  type = string
}

variable "alert_email" {
  description = "Receives alarm and ingestion-failure notifications (confirm the subscription email)."
  type        = string
}

variable "alb_arn_suffix" {
  type = string
}

variable "target_group_arn_suffix" {
  type = string
}

variable "log_group_name" {
  type = string
}

variable "db_instance_id" {
  type = string
}

variable "cluster_arn" {
  type = string
}

variable "jobs_family" {
  type = string
}

variable "schedule_group_name" {
  type = string
}
