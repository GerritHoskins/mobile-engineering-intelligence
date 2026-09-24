terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
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
    tags = {
      project    = "mobile-engineering-intelligence"
      env        = "dev"
      managed_by = "terraform"
    }
  }
}

locals {
  name = "mei-dev"
}

module "network" {
  source = "../../modules/network"

  name = local.name
}

module "database" {
  source = "../../modules/database"

  name       = local.name
  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_subnet_ids
}

module "service" {
  source = "../../modules/service"

  name              = local.name
  region            = var.region
  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
  allowed_cidrs     = var.allowed_cidrs
  image_tag         = var.image_tag

  db_host              = module.database.address
  db_port              = module.database.port
  db_name              = module.database.db_name
  db_secret_arn        = module.database.master_user_secret_arn
  db_security_group_id = module.database.security_group_id
}

module "github_oidc" {
  source = "../../modules/github_oidc"

  name                  = local.name
  subject_prefix        = var.github_oidc_subject_prefix
  ecr_repository_arn    = module.service.ecr_repository_arn
  existing_provider_arn = var.existing_github_oidc_provider_arn
}
