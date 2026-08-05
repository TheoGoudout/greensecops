package greensecops.iac_terraform.reliability.cloudwatch_log_group_no_retention_test

import data.greensecops.iac_terraform.reliability.cloudwatch_log_group_no_retention
import rego.v1

# Mirrors app.services.terraform.hcl_parser.merge_terraform_configs: `resource`
# is a list of single-key objects nested {type: {name: attrs}}, and source
# metadata rides along under double-underscore keys.

_res(attrs) := {"resource": [{"aws_cloudwatch_log_group": {"api": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 9},
	attrs,
)}}]}

test_violation_retention_absent if {
	violations := cloudwatch_log_group_no_retention.violations with input as _res({"name": "/aws/lambda/api"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_cloudwatch_log_group.api"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_violation_retention_is_zero_meaning_never_expire if {
	violations := cloudwatch_log_group_no_retention.violations with input as _res({"retention_in_days": 0})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_cloudwatch_log_group.api"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_no_violation_retention_is_thirty_days if {
	violations := cloudwatch_log_group_no_retention.violations with input as _res({"retention_in_days": 30})
	count(violations) == 0
}
