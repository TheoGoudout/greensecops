# METADATA
# title: Lambda function URL with no auth
# description: A live Lambda function has a Function URL configured with AuthType NONE, making it callable by anyone on the internet without any IAM authentication.
# custom:
#   severity: critical
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws lambda get-function-url-config --function-name my-fn
#       # AuthType: NONE
#     good: |
#       aws lambda get-function-url-config --function-name my-fn
#       # AuthType: AWS_IAM
#     fix: |
#       Set the function URL's auth type to AWS_IAM, or remove the function URL and front it with API Gateway if public access is genuinely required.
package greensecops.cloud_aws.security.lambda_public_function_url

import rego.v1

violations contains violation if {
	some fn in input.lambda_functions
	fn.public_url
	violation := {
		"rule": "lambda_public_function_url",
		"severity": "critical",
		"category": "security",
		"resource_type": "aws_lambda_function",
		"resource_id": fn.name,
		"region": fn.region,
		"message": sprintf("Lambda function '%v' has a public (unauthenticated) function URL.", [fn.name]),
	}
}
