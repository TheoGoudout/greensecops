package greensecops.iac_terraform.security.sqs_queue_unencrypted_test

import data.greensecops.iac_terraform.security.sqs_queue_unencrypted
import rego.v1

# Mirrors app.services.terraform.hcl_parser.merge_terraform_configs: `resource`
# is a list of single-key objects nested {type: {name: attrs}}, and source
# metadata rides along under double-underscore keys.

_res(attrs) := {"resource": [{"aws_sqs_queue": {"jobs": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 9},
	attrs,
)}}]}

test_violation_no_encryption_configured if {
	violations := sqs_queue_unencrypted.violations with input as _res({"name": "jobs"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_sqs_queue.jobs"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_no_violation_sqs_managed_sse_enabled if {
	violations := sqs_queue_unencrypted.violations with input as _res({"sqs_managed_sse_enabled": true})
	count(violations) == 0
}

test_no_violation_kms_key_configured if {
	violations := sqs_queue_unencrypted.violations with input as _res({"kms_master_key_id": "alias/aws/sqs"})
	count(violations) == 0
}
