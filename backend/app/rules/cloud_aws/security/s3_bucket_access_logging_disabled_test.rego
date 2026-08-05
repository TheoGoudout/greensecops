package greensecops.cloud_aws.security.s3_bucket_access_logging_disabled_test

import data.greensecops.cloud_aws.security.s3_bucket_access_logging_disabled as no_logging
import rego.v1

_bucket(logging_enabled) := {"s3_buckets": [{
	"name": "customer-exports",
	"encrypted": true,
	"logging_enabled": logging_enabled,
	"policy_statements": [],
}]}

test_violation_when_logging_is_off if {
	violations := no_logging.violations with input as _bucket(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "customer-exports"
	v.severity == "low"
}

test_no_violation_when_logging_is_on if {
	violations := no_logging.violations with input as _bucket(true)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := no_logging.violations with input as {"s3_buckets": []}
	count(violations) == 0
}

test_each_bucket_is_its_own_finding if {
	violations := no_logging.violations with input as {"s3_buckets": [
		{"name": "exports", "logging_enabled": false},
		{"name": "backups", "logging_enabled": false},
		{"name": "audit-logs", "logging_enabled": true},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
