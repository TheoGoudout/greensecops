# METADATA
# title: Log groups keep their logs forever
# description: "One or more CloudWatch log groups have no retention setting, which means never expire rather than some sensible default. Log volume only grows, so the storage bill and the energy behind it rise every month for data nobody reads — debugging looks at the last few days, and anything older is kept because deleting it was never anybody's job. This is among the easiest reductions available in an AWS account — one setting per group, no code change, and the deletion is retroactive. Reported once for the account with a count and a sample rather than once per group: every Lambda creates a log group, so a per-group finding is a list nobody reads."
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws logs create-log-group --log-group-name /aws/lambda/checkout
#     good: |
#       aws logs put-retention-policy --log-group-name /aws/lambda/checkout \
#         --retention-in-days 30
#     fix: |
#       Set a retention period matched to what the logs are for — 30 days for application debugging, longer only where a compliance obligation actually says so. Where you want the long tail without the cost, export to S3 and let a lifecycle rule move it to Glacier.
package greensecops.cloud_aws.energy.cloudwatch_log_group_no_retention

import rego.v1

_gigabyte := 1073741824

# Aggregated to one finding for the account. Every Lambda creates a log group,
# so a modest account has hundreds, and one finding per group turned a real
# gap into a wall the reader scrolls past. The count is the signal; the sample
# is there so the finding is actionable without a second query.
_sample_limit := 5

_sample(names) := concat(", ", array.slice(sort(names), 0, _sample_limit))

_suffix(names) := "" if count(names) <= _sample_limit

_suffix(names) := sprintf(" and %v more", [count(names) - _sample_limit]) if count(names) > _sample_limit

_unbounded := {group.name |
	some group in input.cloudwatch_log_groups
	group.name != ""
	object.get(group, "retention_days", null) == null
}

_stored_gb := round(sum([bytes |
	some group in input.cloudwatch_log_groups
	group.name != ""
	object.get(group, "retention_days", null) == null
	bytes := object.get(group, "stored_bytes", 0)
]) / _gigabyte)

violations contains violation if {
	names := _unbounded
	count(names) > 0

	violation := {
		"rule": "cloudwatch_log_group_no_retention",
		"severity": "medium",
		"category": "energy",
		"resource_type": "aws_cloudwatch_log_group",
		"resource_id": "account",
		"message": sprintf("%v log group(s) never expire and already hold about %v GB between them, growing every month for data nothing reads: %v%v.", [count(names), _stored_gb, _sample(names), _suffix(names)]),
		"context": _sample(names),
		"discriminator": "account",
	}
}
