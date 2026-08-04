# METADATA
# title: Lambda function URL requires no authentication
# description: An aws_lambda_function_url sets authorization_type = "NONE", so the function's HTTPS endpoint is invokable by anyone who knows the URL. There is no API Gateway in front of it, which means no authorizer, no throttling and no WAF — the function itself is the entire security boundary, and it is billed per invocation, so an unauthenticated URL is both an access-control problem and an open cost channel.
# custom:
#   severity: critical
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_lambda_function_url" "api" {
#         function_name      = aws_lambda_function.api.function_name
#         authorization_type = "NONE"
#       }
#     good: |
#       resource "aws_lambda_function_url" "api" {
#         function_name      = aws_lambda_function.api.function_name
#         authorization_type = "AWS_IAM"
#       }
#     fix: |
#       Set authorization_type = "AWS_IAM" so callers must sign their requests. If the endpoint has to be reachable by unauthenticated clients, put API Gateway or CloudFront in front of it so there is somewhere to attach an authorizer, a rate limit and a WAF.
package greensecops.iac_terraform.security.lambda_public_function_url

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, url in res.aws_lambda_function_url
	url.authorization_type == "NONE"

	violation := {
		"rule": "lambda_public_function_url",
		"severity": "critical",
		"category": "security",
		"resource_address": sprintf("aws_lambda_function_url.%v", [name]),
		"file_path": object.get(url, "__tf_file", ""),
		"line_start": object.get(url, "__start_line__", null),
		"line_end": object.get(url, "__end_line__", null),
		"message": sprintf("Lambda function URL '%v' uses authorization_type = \"NONE\", so anyone with the URL can invoke the function.", [name]),
	}
}
