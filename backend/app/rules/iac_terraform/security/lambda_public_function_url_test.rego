package greensecops.iac_terraform.security.lambda_public_function_url_test

import data.greensecops.iac_terraform.security.lambda_public_function_url
import rego.v1

# Mirrors app.services.terraform.hcl_parser.merge_terraform_configs: `resource`
# is a list of single-key objects nested {type: {name: attrs}}, and source
# metadata rides along under double-underscore keys.

_res(attrs) := {"resource": [{"aws_lambda_function_url": {"api": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 9},
	attrs,
)}}]}

test_violation_authorization_type_none if {
	violations := lambda_public_function_url.violations with input as _res({"authorization_type": "NONE"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_lambda_function_url.api"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_no_violation_authorization_type_aws_iam if {
	violations := lambda_public_function_url.violations with input as _res({"authorization_type": "AWS_IAM"})
	count(violations) == 0
}

test_no_violation_authorization_type_absent if {
	violations := lambda_public_function_url.violations with input as _res({"function_name": "api"})
	count(violations) == 0
}
