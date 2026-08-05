# METADATA
# title: IAM policy grants a wildcard action
# description: A customer-managed IAM policy has an Allow statement with Action set to "*" (or a service-wide "service:*"), granting far more permission than almost any real workload needs.
# custom:
#   severity: critical
#   severity_weight: 4.0
#   detection: cloud_posture
#   examples:
#     bad: |
#       {"Effect": "Allow", "Action": "*", "Resource": "*"}
#     good: |
#       {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": "arn:aws:s3:::my-bucket/*"}
#     fix: |
#       Enumerate the specific actions the policy's principal actually needs instead of a wildcard.
package greensecops.cloud_aws.security.iam_policy_wildcard_action

import rego.v1

violations contains violation if {
	some policy in input.iam_policies
	some stmt in policy.statements
	stmt.effect == "Allow"
	some action in stmt.actions
	is_wildcard_action(action)
	violation := {
		"rule": "iam_policy_wildcard_action",
		"severity": "critical",
		"category": "security",
		"resource_type": "aws_iam_policy",
		"resource_id": policy.arn,
		"message": sprintf("IAM policy '%v' grants wildcard action '%v'.", [policy.name, action]),
	}
}

is_wildcard_action(action) if action == "*"

is_wildcard_action(action) if endswith(action, ":*")
