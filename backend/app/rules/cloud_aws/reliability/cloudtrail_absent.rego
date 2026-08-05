# METADATA
# title: Account has no CloudTrail trail at all
# description: The scan found no CloudTrail trail in the account. This is distinct from cloudtrail_logging_disabled, which needs a trail to exist before it can report one that stopped — an account with no trail produces no finding from that rule at all, which is the wrong answer to the more serious problem. Without a trail there is no record of who did what, so an incident cannot be reconstructed after the fact and no amount of later configuration recovers the missing history.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws cloudtrail describe-trails
#       # {"trailList": []}
#     good: |
#       aws cloudtrail create-trail --name org-audit \
#         --s3-bucket-name audit-logs --is-multi-region-trail
#       aws cloudtrail start-logging --name org-audit
#     fix: |
#       Create a multi-region trail writing to a dedicated bucket in an account the workload cannot write to, and start logging on it. Enable log-file validation so tampering is detectable.
package greensecops.cloud_aws.reliability.cloudtrail_absent

import rego.v1

# The collector returns [] both for "no trails" and for "we lacked permission
# to list them", and cannot tell those apart. Reporting is the right side to
# err on: a missing audit trail is worth a look either way, and the message
# says what to check.
#
# The key must be *present* though, not merely empty. collect_account_resources
# always emits all eight resource keys, so an absent one means the document is
# not a cloud snapshot at all — and a rule that fires on a missing key fires on
# every document in every other engine, which is exactly what the cross-domain
# check in scripts/validate_examples.py caught.
violations contains violation if {
	trails := input.cloudtrail_trails
	is_array(trails)
	count(trails) == 0

	violation := {
		"rule": "cloudtrail_absent",
		"severity": "high",
		"category": "reliability",
		"resource_type": "aws_cloudtrail_trail",
		"resource_id": "account",
		"message": "No CloudTrail trail was found in this account, so API activity is not being recorded. If a trail does exist, check that the scanning role is allowed to call cloudtrail:DescribeTrails.",
	}
}
