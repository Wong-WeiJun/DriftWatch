terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "driftwatch-development-703477452145"
    key    = "terraform.tfstate"
    region = "ap-southeast-2"
  }
}

data "aws_caller_identity" "acc" {}                               #get user id
data "aws_availability_zones" "available" { state = "available" } #get AZs where state=available

locals {
  account_id = data.aws_caller_identity.acc.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
  name       = "driftwatch-${var.environment}"

  common_tags = {
    Project     = "driftwatch"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

module "s3" {
  source     = "./modules/s3"
  name       = local.name
  account_id = local.account_id
  tags       = local.common_tags
}

module "vpc" {
  source = "./modules/vpc"
  name   = local.name
  azs    = local.azs
  tags   = local.common_tags
}

module "sns" {
  source      = "./modules/sns"
  name        = local.name
  alert_email = var.alert_email
  tags        = local.common_tags
}

module "ecs" {
  source             = "./modules/ecs"
  name               = local.name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  public_subnet_ids  = module.vpc.public_subnet_ids
  ecr_image_uri      = var.ecr_image_uri
  drift_table_name   = "driftwatch-events-${var.environment}"
  sns_topic_arn      = module.sns.topic_arn
  state_bucket       = module.s3.state_bucket_name
  aws_region         = var.aws_region
  account_id         = local.account_id
  tags               = local.common_tags
}

# ONLY USED TO GET ECR REPOSITORY URI
# resource "aws_ecr_repository" "app" {
#   name                 = "driftwatch-development"
#   image_tag_mutability = "MUTABLE"
#
#   image_scanning_configuration { scan_on_push = true }
#
#   tags = local.common_tags
# }
#
# output "ecr_repo_url" {
#   value = aws_ecr_repository.app.repository_url
# }
