package greensecops.cloud_aws.security.kms_key_rotation_disabled_test

import data.greensecops.cloud_aws.security.kms_key_rotation_disabled as no_rotation
import rego.v1

# The collector filters to customer-managed, enabled keys before this rule sees
# them, so every entry is one whose rotation the account controls.

_key(rotation_enabled) := {"kms_keys": [{
	"id": "abc-123",
	"region": "eu-west-1",
	"description": "application data",
	"rotation_enabled": rotation_enabled,
}]}

test_violation_when_rotation_is_off if {
	violations := no_rotation.violations with input as _key(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "abc-123"
	v.severity == "medium"
}

test_no_violation_when_rotation_is_on if {
	violations := no_rotation.violations with input as _key(true)
	count(violations) == 0
}

test_no_violation_for_an_account_with_no_customer_keys if {
	violations := no_rotation.violations with input as {"kms_keys": []}
	count(violations) == 0
}

test_each_key_is_its_own_finding if {
	violations := no_rotation.violations with input as {"kms_keys": [
		{"id": "abc-123", "region": "eu-west-1", "rotation_enabled": false},
		{"id": "def-456", "region": "us-east-1", "rotation_enabled": false},
		{"id": "ghi-789", "region": "us-east-1", "rotation_enabled": true},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
