variable "environment" {
  description = "shows deployment environment"
  type        = string
}

variable "alert_email" {
  description = "Email address for notifications"
  type        = string
}

variable "aws_region" {
  description = "Region used for the environment"
  type        = string
}

variable "ecr_image_uri" {
  description = "Image URI used"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in owner/repo format for OIDC trust"
  type        = string
  default     = "Wong-WeiJun/DriftWatch"
}
