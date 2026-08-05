package greensecops.cloud_aws.security.s3_bucket_public_policy_test

import data.greensecops.cloud_aws.security.s3_bucket_public_policy as public_policy
import rego.v1

_bucket(statements) := {"s3_buckets": [{
	"name": "assets",
	"policy_statements": statements,
}]}

_statement(effect, principals, has_condition) := {
	"effect": effect,
	"actions": ["s3:GetObject"],
	"resources": ["arn:aws:s3:::assets/*"],
	"principals": principals,
	"has_condition": has_condition,
}

test_violation_for_a_wildcard_principal if {
	violations := public_policy.violations with input as _bucket([_statement("Allow", ["*"], false)])
	count(violations) == 1
	some v in violations
	v.resource_id == "assets"
	v.severity == "critical"
}

# The long spelling of "everyone" — every account's root, which is every
# account.
test_violation_for_the_wildcard_account_root_spelling if {
	violations := public_policy.violations with input as _bucket([_statement("Allow", ["arn:aws:iam::*:root"], false)])
	count(violations) == 1
}

# A condition is the supported way to scope a wildcard principal, so reporting
# it would fire on the recommended pattern.
test_no_violation_when_the_statement_carries_a_condition if {
	violations := public_policy.violations with input as _bucket([_statement("Allow", ["*"], true)])
	count(violations) == 0
}

test_no_violation_for_a_deny_statement if {
	violations := public_policy.violations with input as _bucket([_statement("Deny", ["*"], false)])
	count(violations) == 0
}

test_no_violation_for_a_named_principal if {
	violations := public_policy.violations with input as _bucket([_statement(
		"Allow",
		["arn:aws:iam::123456789012:role/reader"],
		false,
	)])
	count(violations) == 0
}

test_no_violation_for_a_bucket_with_no_policy if {
	violations := public_policy.violations with input as _bucket([])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := public_policy.violations with input as {"s3_buckets": []}
	count(violations) == 0
}

test_the_message_names_the_granted_action if {
	violations := public_policy.violations with input as _bucket([_statement("Allow", ["*"], false)])
	some v in violations
	contains(v.message, "s3:GetObject")
}

test_each_public_statement_is_its_own_finding if {
	violations := public_policy.violations with input as _bucket([
		_statement("Allow", ["*"], false),
		_statement("Allow", ["*"], false),
		_statement("Allow", ["arn:aws:iam::123456789012:root"], false),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
