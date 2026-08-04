package greensecops.cloud_aws.security.iam_policy_wildcard_action_test

import data.greensecops.cloud_aws.security.iam_policy_wildcard_action as wildcard_action
import rego.v1

# The collector fetches the default version of each policy and flattens its
# statements, so `actions` and `resources` are always lists by the time a rule
# sees them even where the document used a bare string.

_policies(statements) := {"iam_policies": [{
	"name": "app",
	"arn": "arn:aws:iam::123456789012:policy/app",
	"statements": statements,
}]}

_stmt(effect, actions, resources) := {
	"effect": effect,
	"actions": actions,
	"resources": resources,
}

test_violation_for_a_bare_wildcard_action if {
	violations := wildcard_action.violations with input as _policies([_stmt("Allow", ["*"], ["*"])])
	count(violations) == 1
	some v in violations
	v.resource_id == "arn:aws:iam::123456789012:policy/app"
	v.severity == "critical"
}

test_violation_for_a_service_wide_wildcard if {
	violations := wildcard_action.violations with input as _policies([_stmt("Allow", ["s3:*"], ["arn:aws:s3:::b/*"])])
	count(violations) == 1
	some v in violations
	contains(v.message, "s3:*")
}

test_violation_for_iam_wildcard_which_allows_self_escalation if {
	violations := wildcard_action.violations with input as _policies([_stmt("Allow", ["iam:*"], ["*"])])
	count(violations) == 1
}

test_no_violation_for_named_actions if {
	violations := wildcard_action.violations with input as _policies([_stmt(
		"Allow",
		["s3:GetObject", "s3:PutObject"],
		["arn:aws:s3:::b/*"],
	)])
	count(violations) == 0
}

# A prefix wildcard inside an action name is scoped to those actions.
test_no_violation_for_a_partial_action_prefix if {
	violations := wildcard_action.violations with input as _policies([_stmt("Allow", ["s3:Get*"], ["arn:aws:s3:::b/*"])])
	count(violations) == 0
}

# A Deny on everything is a guardrail, not a grant.
test_no_violation_for_a_deny_statement if {
	violations := wildcard_action.violations with input as _policies([_stmt("Deny", ["*"], ["*"])])
	count(violations) == 0
}

test_no_violation_for_an_account_with_no_policies if {
	violations := wildcard_action.violations with input as {"iam_policies": []}
	count(violations) == 0
}

test_each_wildcard_action_is_its_own_finding if {
	violations := wildcard_action.violations with input as _policies([
		_stmt("Allow", ["s3:*"], ["*"]),
		_stmt("Allow", ["sqs:*"], ["*"]),
		_stmt("Allow", ["kms:Decrypt"], ["*"]),
	])
	count(violations) == 2
}
