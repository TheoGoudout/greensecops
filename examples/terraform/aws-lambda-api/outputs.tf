output "function_url" {
  description = "Public HTTPS endpoint of the API function."
  value       = aws_lambda_function_url.api.function_url
}

output "queue_url" {
  description = "URL of the background job queue."
  value       = aws_sqs_queue.jobs.url
}
