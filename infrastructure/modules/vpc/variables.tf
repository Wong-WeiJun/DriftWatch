variable "name" {
  description = "Base name for the bucket"
  type        = string
}

variable "azs" {
  description = "List of AZs available for subnets to deploy into"
  type        = list(string)
}

variable "tags" {
  type = map(string)
}
