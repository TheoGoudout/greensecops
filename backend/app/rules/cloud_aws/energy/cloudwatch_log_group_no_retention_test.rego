package greensecops.cloud_aws.energy.cloudwatch_log_group_no_retention_test

import data.greensecops.cloud_aws.energy.cloudwatch_log_group_no_retention as no_retention
import rego.v1

_group(retention_days, stored_bytes) := {"cloudwatch_log_groups": [{
	"name": "/aws/lambda/checkout",
	"region": "eu-west-1",
	"retention_days": retention_days,
	"kms_key_id": null,
	"stored_bytes": stored_bytes,
}]}

test_violation_when_retention_is_unset if {
	violations := no_retention.violations with input as _group(null, 5368709120)
	count(violations) == 1
	some v in violations
	v.resource_id == "account"
	v.category == "energy"
	contains(v.message, "/aws/lambda/checkout")
}

test_no_violation_when_retention_is_set if {
	violations := no_retention.violations with input as _group(30, 5368709120)
	count(violations) == 0
}

# Rego normalises a whole-number division to an int, which sprintf's %f rejects
# — the message uses round() and %v so both cases render.
test_the_message_reports_whole_gigabytes if {
	violations := no_retention.violations with input as _group(null, 5368709120)
	some v in violations
	contains(v.message, "5 GB")
}

test_the_message_renders_a_fractional_size if {
	violations := no_retention.violations with input as _group(null, 1288490188)
	some v in violations
	contains(v.message, "1 GB")
}

test_no_violation_for_an_empty_account if {
	violations := no_retention.violations with input as {"cloudwatch_log_groups": []}
	count(violations) == 0
}

# Every Lambda creates a log group, so one finding per group buried the signal.
# The count is the finding; the sample makes it actionable.
test_one_account_level_finding_however_many_groups if {
	violations := no_retention.violations with input as {"cloudwatch_log_groups": [
		{"name": "/aws/lambda/a", "region": "eu-west-1", "retention_days": null, "stored_bytes": 1073741824},
		{"name": "/aws/lambda/b", "region": "eu-west-1", "retention_days": null, "stored_bytes": 1073741824},
		{"name": "/aws/lambda/c", "region": "eu-west-1", "retention_days": 7, "stored_bytes": 0},
	]}
	count(violations) == 1
	some v in violations
	contains(v.message, "2 log group(s)")
	contains(v.message, "2 GB")
}

test_the_sample_is_capped_and_the_remainder_counted if {
	groups := [{"name": sprintf("/aws/lambda/%02d", [i]), "region": "eu-west-1", "retention_days": null, "stored_bytes": 0} |
		some i in numbers.range(1, 8)
	]
	violations := no_retention.violations with input as {"cloudwatch_log_groups": groups}
	some v in violations
	contains(v.message, "8 log group(s)")
	contains(v.message, "and 3 more")
}
