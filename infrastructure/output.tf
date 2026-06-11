output "state_bucket" {
  value = module.s3.state_bucket_name
}

output "sns_topic_arn" {
  value = module.sns.topic_arn
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "api_url" {
  value = "http://${module.ecs.alb_dns_name}"
}

output "alb_dns_name" {
  value = module.ecs.alb_dns_name
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}
