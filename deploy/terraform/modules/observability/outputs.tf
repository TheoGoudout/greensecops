output "alarm_topic_arn" {
  description = "SNS topic every alarm publishes to. Subscribe PagerDuty, Slack or another address to it."
  value       = aws_sns_topic.alarms.arn
}
