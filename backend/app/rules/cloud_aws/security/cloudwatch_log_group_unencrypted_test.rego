package greensecops.cloud_aws.security.cloudwatch_log_group_unencrypted_test

import data.greensecops.cloud_aws.security.cloudwatch_log_group_unencrypted as unencrypted
import rego.v1

_group(kms_key_id) := {"cloudwatch_log_groups": [{
	"name": "/aws/lambda/checkout",
	"region": "eu-west-1",
	"retention_days": 30,
	"kms_key_id": kms_key_id,
	"stored_bytes": 1024,
}]}

test_violation_when_no_key_is_associated if {
	violations := unencrypted.violations with input as _group(null)
	count(violations) == 1
	some v in violations
	v.resource_id == "account"
	contains(v.message, "/aws/lambda/checkout")
}

test_no_violation_when_a_key_is_associated if {
	violations := unencrypted.violations with input as _group("arn:aws:kms:eu-west-1:123456789012:key/abc-123")
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := unencrypted.violations with input as {"cloudwatch_log_groups": []}
	count(violations) == 0
}

test_one_account_level_finding_however_many_groups if {
	violations := unencrypted.violations with input as {"cloudwatch_log_groups": [
		{"name": "/aws/lambda/a", "region": "eu-west-1", "kms_key_id": null},
		{"name": "/aws/lambda/b", "region": "eu-west-1", "kms_key_id": null},
		{"name": "/aws/lambda/c", "region": "eu-west-1", "kms_key_id": "arn:...key/x"},
	]}
	count(violations) == 1
	some v in violations
	contains(v.message, "2 log group(s)")
	v.discriminator == "account"
}
