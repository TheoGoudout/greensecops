package greensecops.cloud_aws.security.iam_access_key_unused_test

import data.greensecops.cloud_aws.security.iam_access_key_unused as unused_key
import rego.v1

_user(extra) := {"iam_users": [object.union(
	{
		"name": "deploy",
		"mfa_enabled": true,
		"console_access": false,
		"access_key_age_days": null,
		"access_key_unused_days": null,
	},
	extra,
)]}

test_violation_for_a_key_unused_for_months if {
	violations := unused_key.violations with input as _user({"access_key_unused_days": 200})
	count(violations) == 1
	some v in violations
	v.resource_id == "deploy"
}

test_no_violation_for_a_key_in_active_use if {
	violations := unused_key.violations with input as _user({"access_key_unused_days": 2})
	count(violations) == 0
}

test_no_violation_exactly_at_the_bound if {
	violations := unused_key.violations with input as _user({"access_key_unused_days": 90})
	count(violations) == 0
}

test_no_violation_when_usage_could_not_be_read if {
	violations := unused_key.violations with input as _user({"access_key_unused_days": null})
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := unused_key.violations with input as {"iam_users": []}
	count(violations) == 0
}

test_the_message_states_the_idle_period if {
	violations := unused_key.violations with input as _user({"access_key_unused_days": 200})
	some v in violations
	contains(v.message, "200")
}

# The two key rules are independent: a young key can be idle, and an old key
# can be in daily use.
test_a_young_but_idle_key_is_still_reported if {
	violations := unused_key.violations with input as _user({
		"access_key_age_days": 10,
		"access_key_unused_days": 100,
	})
	count(violations) == 1
}
