package greensecops.cloud_aws.security.cloudtrail_log_validation_disabled_test

import data.greensecops.cloud_aws.security.cloudtrail_log_validation_disabled as no_validation
import rego.v1

_trail(validation) := {"cloudtrail_trails": [{
	"name": "audit",
	"region": "eu-west-1",
	"is_logging": true,
	"is_multi_region": true,
	"log_file_validation_enabled": validation,
	"kms_key_id": null,
}]}

test_violation_when_validation_is_off if {
	violations := no_validation.violations with input as _trail(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "audit"
	v.severity == "medium"
}

test_no_violation_when_validation_is_on if {
	violations := no_validation.violations with input as _trail(true)
	count(violations) == 0
}

test_no_violation_for_an_account_with_no_trails if {
	violations := no_validation.violations with input as {"cloudtrail_trails": []}
	count(violations) == 0
}

# A trail that is not logging is still worth flagging for validation — the two
# settings are independent, and turning logging back on should not then leave
# an unverifiable log.
test_violation_applies_to_a_stopped_trail_too if {
	violations := no_validation.violations with input as {"cloudtrail_trails": [{
		"name": "audit",
		"region": "eu-west-1",
		"is_logging": false,
		"is_multi_region": true,
		"log_file_validation_enabled": false,
		"kms_key_id": null,
	}]}
	count(violations) == 1
}

test_each_trail_is_its_own_finding if {
	violations := no_validation.violations with input as {"cloudtrail_trails": [
		{"name": "audit", "region": "eu-west-1", "log_file_validation_enabled": false},
		{"name": "backup", "region": "us-east-1", "log_file_validation_enabled": false},
		{"name": "ok", "region": "us-east-1", "log_file_validation_enabled": true},
	]}
	count(violations) == 2
}
