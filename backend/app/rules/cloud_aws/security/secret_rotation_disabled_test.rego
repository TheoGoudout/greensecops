package greensecops.cloud_aws.security.secret_rotation_disabled_test

import data.greensecops.cloud_aws.security.secret_rotation_disabled as no_rotation
import rego.v1

_secret(rotation_enabled, rotation_days) := {"secrets": [{
	"name": "prod/db/password",
	"region": "eu-west-1",
	"rotation_enabled": rotation_enabled,
	"rotation_days": rotation_days,
	"kms_key_id": null,
}]}

test_violation_when_rotation_is_off if {
	violations := no_rotation.violations with input as _secret(false, null)
	count(violations) == 1
	some v in violations
	v.resource_id == "prod/db/password"
	v.severity == "medium"
}

test_no_violation_when_rotation_is_on if {
	violations := no_rotation.violations with input as _secret(true, 30)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := no_rotation.violations with input as {"secrets": []}
	count(violations) == 0
}

# The collector never reads a secret's value, so nothing here can leak one —
# the finding names the secret, not its contents.
test_the_message_does_not_carry_a_value if {
	violations := no_rotation.violations with input as _secret(false, null)
	some v in violations
	contains(v.message, "prod/db/password")
}

test_each_secret_is_its_own_finding if {
	violations := no_rotation.violations with input as {"secrets": [
		{"name": "prod/db/password", "region": "eu-west-1", "rotation_enabled": false},
		{"name": "prod/api/key", "region": "eu-west-1", "rotation_enabled": false},
		{"name": "prod/db/replica", "region": "eu-west-1", "rotation_enabled": true},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
