terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = "ap-southeast-1"
  profile = "default"
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


