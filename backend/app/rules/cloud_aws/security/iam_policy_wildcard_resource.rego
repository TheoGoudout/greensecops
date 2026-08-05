# METADATA
# title: IAM policy grants an action on every resource
# description: A live IAM policy has an Allow statement whose Resource is "*", so whatever actions it grants apply to every resource in the account. The companion iam_policy_wildcard_action rule catches the other half of the same mistake — an unbounded verb — and the two are independent. A narrow action on every resource is the more common of the two and the easier to overlook, because the action list reads as deliberate.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws iam create-policy --policy-name reader --policy-document '{
#         "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "*"}]}'
#     good: |
#       aws iam create-policy --policy-name reader --policy-document '{
#         "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"],
#                        "Resource": "arn:aws:s3:::reports-bucket/*"}]}'
#     fix: |
#       Name the ARNs the statement is for, using a prefix wildcard on the resource path rather than a bare "*". Some actions genuinely cannot be scoped, but they are few — check the service's documentation before concluding this one is among them.
package greensecops.cloud_aws.security.iam_policy_wildcard_resource

import rego.v1

violations contains violation if {
	some policy in input.iam_policies
	some stmt in policy.statements
	stmt.effect == "Allow"
	some resource in stmt.resources
	resource == "*"

	violation := {
		"rule": "iam_policy_wildcard_resource",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_iam_policy",
		"resource_id": policy.arn,
		"message": sprintf("IAM policy '%v' allows %v on every resource in the account.", [policy.name, concat(", ", stmt.actions)]),
		"discriminator": concat(",", stmt.actions),
	}
}
