package greensecops.iac_terraform.security.iam_policy_wildcard_action_test

import data.greensecops.iac_terraform.security.iam_policy_wildcard_action as wildcard_action
import rego.v1

# hcl2 does not evaluate jsonencode(), so a policy document reaches the rule as
# opaque text in both the jsonencode and heredoc spellings. Matching is on that
# text, the same approach hardcoded_credentials_in_tf takes.

_policy(res_type, attrs) := {"resource": [{res_type: {"app": object.union(
	{"__tf_file": "iam.tf", "__start_line__": 3, "__end_line__": 12},
	attrs,
)}}]}

test_violation_for_a_bare_wildcard_action if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"policy": "${jsonencode({Statement = [{Effect = \"Allow\", Action = \"*\", Resource = \"*\"}]})}"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_iam_policy.app"
	v.file_path == "iam.tf"
}

test_violation_for_a_service_wide_wildcard if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"policy": "${jsonencode({Statement = [{Effect = \"Allow\", Action = [\"s3:*\"], Resource = \"arn:aws:s3:::b/*\"}]})}"})
	count(violations) == 1
}

test_violation_for_the_json_spelling if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"policy": "{\"Statement\": [{\"Effect\": \"Allow\", \"Action\": \"*\", \"Resource\": \"*\"}]}"})
	count(violations) == 1
}

test_violation_for_an_inline_role_policy if {
	violations := wildcard_action.violations with input as _policy("aws_iam_role_policy", {"policy": "${jsonencode({Statement = [{Effect = \"Allow\", Action = \"iam:*\", Resource = \"*\"}]})}"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_iam_role_policy.app"
}

test_no_violation_for_named_actions if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"policy": "${jsonencode({Statement = [{Effect = \"Allow\", Action = [\"s3:GetObject\", \"s3:PutObject\"], Resource = \"arn:aws:s3:::b/*\"}]})}"})
	count(violations) == 0
}

# A wildcard Resource with named actions is iam_policy_wildcard_resource's
# finding in the cloud engine, not this rule's.
test_no_violation_for_a_wildcard_resource_alone if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"policy": "${jsonencode({Statement = [{Effect = \"Allow\", Action = [\"s3:GetObject\"], Resource = \"*\"}]})}"})
	count(violations) == 0
}

# A document that only denies is a guardrail.
test_no_violation_for_a_deny_only_document if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"policy": "${jsonencode({Statement = [{Effect = \"Deny\", Action = \"*\", Resource = \"*\"}]})}"})
	count(violations) == 0
}

# A document mixing Allow and Deny still reports: the text match cannot say
# which statement the wildcard belongs to, and reporting is the safe side.
test_violation_when_a_document_mixes_allow_and_deny if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"policy": "${jsonencode({Statement = [{Effect = \"Deny\", Action = \"iam:*\", Resource = \"*\"}, {Effect = \"Allow\", Action = \"s3:GetObject\", Resource = \"*\"}]})}"})
	count(violations) == 1
}

test_no_violation_when_the_policy_is_not_a_string if {
	violations := wildcard_action.violations with input as _policy("aws_iam_policy", {"name": "app"})
	count(violations) == 0
}

test_no_violation_for_an_unrelated_resource_type if {
	violations := wildcard_action.violations with input as _policy("aws_s3_bucket", {"policy": "${jsonencode({Statement = [{Effect = \"Allow\", Action = \"*\"}]})}"})
	count(violations) == 0
}
