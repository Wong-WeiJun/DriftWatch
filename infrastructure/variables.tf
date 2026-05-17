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
