variable "name" { type = string }
variable "aws_region" { type = string }
variable "account_id" { type = string }
variable "tags" { type = map(string) }

variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids" { type = list(string) }

variable "ecr_image_uri" { type = string }
variable "drift_table_name" { type = string }
variable "sns_topic_arn" { type = string }
variable "state_bucket" { type = string }
