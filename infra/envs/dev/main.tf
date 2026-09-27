terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # bucket and allowed_account_ids come from backend.hcl (gitignored):
  #   terraform init -backend-config=backend.hcl
  backend "s3" {
    key          = "dev/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = merge(
      {
        project    = "mobile-engineering-intelligence"
        env        = "dev"
        managed_by = "terraform"
      },
      var.tags,
    )
  }
}

locals {
  name = "mei-dev"

  # Either this stack's own VPC, or an existing one (e.g. a platform team's),
  # which must give the private subnets a NAT route for egress.
  network = var.existing_network != null ? var.existing_network : {
    vpc_id             = module.network[0].vpc_id
    public_subnet_ids  = module.network[0].public_subnet_ids
    private_subnet_ids = module.network[0].private_subnet_ids
  }
}

module "network" {
  source = "../../modules/network"
  count  = var.existing_network == null ? 1 : 0

  name = local.name
}

module "database" {
  source = "../../modules/database"

  name       = local.name
  vpc_id     = local.network.vpc_id
  subnet_ids = local.network.private_subnet_ids
}

# Shared between CloudFront (sends it) and the ALB (requires it).
resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

module "service" {
  source = "../../modules/service"

  name                 = local.name
  region               = var.region
  vpc_id               = local.network.vpc_id
  public_subnet_ids    = local.network.public_subnet_ids
  private_subnet_ids   = local.network.private_subnet_ids
  image_tag            = var.image_tag
  origin_verify_secret = random_password.origin_verify.result

  anthropic_aws_workspace_id = var.anthropic_aws_workspace_id

  db_host              = module.database.address
  db_port              = module.database.port
  db_name              = module.database.db_name
  db_secret_arn        = module.database.master_user_secret_arn
  db_security_group_id = module.database.security_group_id
}

module "edge" {
  source = "../../modules/edge"

  name                 = local.name
  alb_dns_name         = module.service.alb_dns_name
  allowed_cidrs        = var.allowed_cidrs
  origin_verify_secret = random_password.origin_verify.result
}

module "secrets" {
  source = "../../modules/secrets"

  name = local.name
}

module "jobs" {
  source = "../../modules/jobs"

  name               = local.name
  region             = var.region
  image              = module.service.image
  cluster_arn        = module.service.cluster_arn
  private_subnet_ids = local.network.private_subnet_ids
  security_group_id  = module.service.service_security_group_id
  log_group_name     = module.service.log_group_name
  schedule_enabled   = var.ingestion_schedule_enabled

  db_host            = module.database.address
  db_port            = module.database.port
  db_name            = module.database.db_name
  db_secret_arn      = module.database.master_user_secret_arn
  vendor_secret_arns = module.secrets.env_to_arn
}

module "observability" {
  source = "../../modules/observability"

  name                    = local.name
  region                  = var.region
  account_id              = var.aws_account_id
  alert_email             = var.alert_email
  alb_arn_suffix          = module.service.alb_arn_suffix
  target_group_arn_suffix = module.service.target_group_arn_suffix
  log_group_name          = module.service.log_group_name
  db_instance_id          = module.database.identifier
  cluster_arn             = module.service.cluster_arn
  jobs_family             = module.jobs.task_definition_family
  schedule_group_name     = module.jobs.schedule_group_name
}

module "github_oidc" {
  source = "../../modules/github_oidc"

  name                  = local.name
  subject_prefix        = var.github_oidc_subject_prefix
  ecr_repository_arn    = module.service.ecr_repository_arn
  existing_provider_arn = var.existing_github_oidc_provider_arn
}
