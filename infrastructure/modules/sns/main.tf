resource "aws_sns_topic" "user_updates" {
  name = "${var.name}-topic"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "email_target" {
  topic_arn = aws_sns_topic.user_updates.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
