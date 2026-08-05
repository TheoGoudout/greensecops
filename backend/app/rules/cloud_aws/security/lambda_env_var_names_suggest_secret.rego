# METADATA
# title: Lambda environment variable looks like a plaintext secret
# description: A Lambda function has an environment variable whose name says it holds a credential. Lambda environment variables are stored with the function configuration and are readable by anyone with lambda GetFunctionConfiguration, which is a far wider set of principals than any secret store would grant — and unlike a secret store, there is no rotation, no access log, and no way to revoke one copy. The name alone is strong evidence here, because nobody calls a variable DATABASE_PASSWORD unless it holds one. Note that this scanner reads variable *names only* and never their values, so the finding cannot itself expose anything.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws lambda update-function-configuration --function-name checkout \
#         --environment 'Variables={DATABASE_PASSWORD=hunter2}'
#     good: |
#       aws lambda update-function-configuration --function-name checkout \
#         --environment 'Variables={DB_SECRET_ARN=arn:aws:secretsmanager:eu-west-1:123456789012:secret:prod/db-AbCdEf}'
#     fix: |
#       Put the value in Secrets Manager or SSM Parameter Store and pass the ARN instead, fetching it at cold start. Rotate the credential afterwards — it has been readable in the function configuration, and in every CloudTrail-less copy of it, for as long as it has been set.
package greensecops.cloud_aws.security.lambda_env_var_names_suggest_secret

import rego.v1

_secret_name_pattern := `(?i)(password|passwd|secret|token|api_?key|private_?key|credential)`

# A name that points at where a secret lives is the fix, not the finding.
_is_reference(name) if regex.match(`(?i)(_arn|_name|_id|_path|_url)$`, name)

violations contains violation if {
	some fn in input.lambda_functions

	some name in fn.environment_names
	regex.match(_secret_name_pattern, name)
	not _is_reference(name)

	violation := {
		"rule": "lambda_env_var_names_suggest_secret",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_lambda_function",
		"resource_id": fn.name,
		"region": fn.region,
		"message": sprintf("Function '%v' has an environment variable named '%v', which reads as a plaintext credential — anyone who can describe the function can read it.", [fn.name, name]),
		"discriminator": name,
	}
}
