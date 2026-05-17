output "state_bucket" {
  value = module.s3.state_bucket_name
}

output "sns_topic_arn" {
  value = module.sns.topic_arn
}

output "vpc_id" {
  value = module.vpc.vpc_id
}
