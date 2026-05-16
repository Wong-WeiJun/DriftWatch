variable "name" {
  description = "Base name for the bucket"
  type        = string
}

variable "account_id" {
  description = "AWS account ID used for unique naming"
}

variable "tags" {
  type = map(string)
}
