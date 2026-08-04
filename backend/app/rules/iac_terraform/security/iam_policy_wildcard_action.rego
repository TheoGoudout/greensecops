# METADATA
# title: IAM policy document grants a wildcard action
# description: An IAM policy defined in Terraform allows a wildcard action — either a bare "*" or a whole service such as "s3:*". The identity holding it can do anything that wildcard covers, including changing its own permissions where the service is IAM, so the policy stops bounding what a compromise can reach. The cloud engine's rule of the same name finds these once they are live; this finds them before they are applied, which is the only point at which the fix is free.
# custom:
#   severity: critical
#   detection: pattern_matching
#   examples:
#     bad: |
#       resource "aws_iam_policy" "app" {
#         name   = "app"
#         policy = jsonencode({
#           Statement = [{ Effect = "Allow", Action = "*", Resource = "*" }]
#         })
#       }
#     good: |
#       resource "aws_iam_policy" "app" {
#         name   = "app"
#         policy = jsonencode({
#           Statement = [{
#             Effect   = "Allow"
#             Action   = ["s3:GetObject", "s3:PutObject"]
#             Resource = "arn:aws:s3:::app-bucket/*"
#           }]
#         })
#       }
#     fix: |
#       Name the actions the identity uses. Start from CloudTrail's record of what it actually called rather than from the service's full action list, and prefer an AWS managed read-only policy over a hand-written wildcard where one fits.
package greensecops.iac_terraform.security.iam_policy_wildcard_action

import rego.v1

# Policy documents reach the parser as opaque strings: jsonencode(...) and
# heredocs both survive as text, and hcl2 does not evaluate the function. So
# this matches on the text rather than walking a parsed document -- the same
# approach hardcoded_credentials_in_tf takes to the same problem.
_policy_types := {
	"aws_iam_policy",
	"aws_iam_role_policy",
	"aws_iam_user_policy",
	"aws_iam_group_policy",
}

_policy_text(attrs) := text if {
	text := attrs.policy
	is_string(text)
}

_policy_text(attrs) := text if {
	text := attrs.inline_policy
	is_string(text)
}

# Matches Action = "*", "Action": "*", and Action = ["s3:*", ...] in both the
# jsonencode and heredoc spellings. Anchored on the key so a wildcard in a
# Resource or a Condition does not match here -- that is a different finding.
_grants_wildcard_action(text) if {
	regex.match(`(?is)"?Action"?\s*[:=]\s*\[?[^\]\n]*"(\*|[a-z0-9-]+:\*)"`, text)
}

# A statement that is explicitly a Deny is a guardrail. This is deliberately
# coarse: a document mixing Allow and Deny still reports, because the text
# match cannot attribute the wildcard to one statement.
_is_deny_only(text) if {
	regex.match(`(?is)"?Effect"?\s*[:=]\s*"Deny"`, text)
	not regex.match(`(?is)"?Effect"?\s*[:=]\s*"Allow"`, text)
}

violations contains violation if {
	some res in input.resource
	some res_type, named in res
	res_type in _policy_types
	some name, attrs in named

	text := _policy_text(attrs)
	_grants_wildcard_action(text)
	not _is_deny_only(text)

	violation := {
		"rule": "iam_policy_wildcard_action",
		"severity": "critical",
		"category": "security",
		"resource_address": sprintf("%v.%v", [res_type, name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"line_start": object.get(attrs, "__start_line__", null),
		"line_end": object.get(attrs, "__end_line__", null),
		"message": sprintf("IAM policy '%v.%v' grants a wildcard action, so whatever holds it can do anything that wildcard covers.", [res_type, name]),
	}
}
