package greensecops.cloud_aws.security.iam_access_key_too_old_test

import data.greensecops.cloud_aws.security.iam_access_key_too_old as stale_key
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

test_violation_for_a_key_older_than_a_year if {
	violations := stale_key.violations with input as _user({"access_key_age_days": 500})
	count(violations) == 1
	some v in violations
	v.resource_id == "deploy"
	v.severity == "medium"
}

test_no_violation_for_a_recently_rotated_key if {
	violations := stale_key.violations with input as _user({"access_key_age_days": 30})
	count(violations) == 0
}

test_no_violation_exactly_at_the_bound if {
	violations := stale_key.violations with input as _user({"access_key_age_days": 365})
	count(violations) == 0
}

# A missing credential report means the age was not measured, which is not
# evidence of an old key — an under-permissioned role must not manufacture
# findings.
test_no_violation_when_the_age_could_not_be_read if {
	violations := stale_key.violations with input as _user({"access_key_age_days": null})
	count(violations) == 0
}

test_no_violation_for_a_user_with_no_static_key if {
	violations := stale_key.violations with input as _user({})
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := stale_key.violations with input as {"iam_users": []}
	count(violations) == 0
}

test_the_message_states_the_age if {
	violations := stale_key.violations with input as _user({"access_key_age_days": 500})
	some v in violations
	contains(v.message, "500")
}

test_each_user_is_its_own_finding if {
	violations := stale_key.violations with input as {"iam_users": [
		{"name": "deploy", "access_key_age_days": 500},
		{"name": "backup", "access_key_age_days": 900},
		{"name": "ci", "access_key_age_days": 10},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
