# METADATA
# title: Lambda function on a deprecated runtime
# description: A live Lambda function runs on a runtime AWS has deprecated (past its official end-of-support date), so it no longer receives security patches and is blocked from configuration updates until migrated.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws lambda get-function-configuration --function-name my-fn
#       # Runtime: python3.7
#     good: |
#       aws lambda get-function-configuration --function-name my-fn
#       # Runtime: python3.12
#     fix: |
#       Migrate the function to a currently supported runtime version.
package greensecops.cloud_aws.maintainability.lambda_deprecated_runtime

import rego.v1

_deprecated_runtimes := {
	# Reviewed against the AWS Lambda runtime deprecation schedule. A runtime
	# missing from this list is silently treated as supported, and nothing but
	# a re-read catches that — see the note in the description.
	"python2.7", "python3.6", "python3.7", "python3.8", "python3.9",
	"nodejs10.x", "nodejs12.x", "nodejs14.x", "nodejs16.x", "nodejs18.x",
	"dotnetcore2.1", "dotnetcore3.1", "dotnet6",
	"ruby2.5", "ruby2.7",
	"go1.x",
	"java8",
}

violations contains violation if {
	some fn in input.lambda_functions
	fn.runtime in _deprecated_runtimes
	violation := {
		"rule": "lambda_deprecated_runtime",
		"severity": "medium",
		"category": "maintainability",
		"resource_type": "aws_lambda_function",
		"resource_id": fn.name,
		"region": fn.region,
		"message": sprintf("Lambda function '%v' runs on deprecated runtime '%v'.", [fn.name, fn.runtime]),
	}
}
