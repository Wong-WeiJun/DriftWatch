variable "name" {
  description = "Base name for the bucket"
  type        = string
}

variable "alert_email" {
  description = "Email address for notifications"
  type        = string
}

variable "tags" {
  type = map(string)
}
