package greensecops.cloud_aws.security.iam_policy_wildcard_resource_test

import data.greensecops.cloud_aws.security.iam_policy_wildcard_resource as wildcard_resource
import rego.v1

# Mirrors what services/cloud/aws_collector._collect_iam_policies produces:
# each policy carries `statements`, each with `effect`, `actions` and
# `resources` already flattened into lists.

_policies(statements) := {"iam_policies": [{
	"name": "reader",
	"arn": "arn:aws:iam::123456789012:policy/reader",
	"statements": statements,
}]}

_stmt(effect, actions, resources) := {
	"effect": effect,
	"actions": actions,
	"resources": resources,
}

test_violation_when_resource_is_a_bare_wildcard if {
	violations := wildcard_resource.violations with input as _policies([_stmt("Allow", ["s3:GetObject"], ["*"])])
	count(violations) == 1
	some v in violations
	v.resource_id == "arn:aws:iam::123456789012:policy/reader"
	contains(v.message, "s3:GetObject")
}

test_no_violation_for_a_scoped_resource if {
	violations := wildcard_resource.violations with input as _policies([_stmt("Allow", ["s3:GetObject"], ["arn:aws:s3:::reports-bucket/*"])])
	count(violations) == 0
}

# A prefix wildcard on a path is scoped; only a bare "*" is unbounded.
test_no_violation_for_a_prefix_wildcard if {
	violations := wildcard_resource.violations with input as _policies([_stmt("Allow", ["s3:GetObject"], ["arn:aws:s3:::reports-*"])])
	count(violations) == 0
}

# A Deny on every resource is a guardrail, not a grant.
test_no_violation_for_a_deny_statement if {
	violations := wildcard_resource.violations with input as _policies([_stmt("Deny", ["s3:DeleteBucket"], ["*"])])
	count(violations) == 0
}

test_violation_when_one_of_several_resources_is_a_wildcard if {
	violations := wildcard_resource.violations with input as _policies([_stmt(
		"Allow",
		["s3:GetObject"],
		["arn:aws:s3:::reports-bucket/*", "*"],
	)])
	count(violations) == 1
}

test_each_offending_statement_is_its_own_finding if {
	violations := wildcard_resource.violations with input as _policies([
		_stmt("Allow", ["s3:GetObject"], ["*"]),
		_stmt("Allow", ["sqs:SendMessage"], ["*"]),
		_stmt("Allow", ["kms:Decrypt"], ["arn:aws:kms:eu-west-1:1:key/abc"]),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}

test_no_violation_when_the_account_has_no_policies if {
	violations := wildcard_resource.violations with input as {"iam_policies": []}
	count(violations) == 0
}

# This rule and iam_policy_wildcard_action catch independent halves of the same
# mistake; a policy can trip either without the other.
test_fires_independently_of_the_wildcard_action_rule if {
	violations := wildcard_resource.violations with input as _policies([_stmt("Allow", ["*"], ["arn:aws:s3:::b/*"])])
	count(violations) == 0
}
