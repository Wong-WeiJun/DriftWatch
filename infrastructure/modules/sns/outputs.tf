output "topic_arn" {
  value = aws_sns_topic.user_updates.arn
}

output "sns_subscription_id" {
  value = aws_sns_topic_subscription.email_target.id
}

