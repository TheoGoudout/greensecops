# METADATA
# title: Log group keeps its logs forever
# description: A CloudWatch log group has no retention setting, which means never expire rather than some sensible default. Log volume only grows, so the storage bill and the energy behind it rise every month for data nobody reads — debugging looks at the last few days, and anything older is kept because deleting it was never anybody's job. This is among the easiest reductions available in an AWS account — one setting per group, no code change, and the deletion is retroactive.
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

violations contains violation if {
	some group in input.cloudwatch_log_groups

	group.name != ""
	object.get(group, "retention_days", null) == null

	stored_gb := round(object.get(group, "stored_bytes", 0) / _gigabyte)

	violation := {
		"rule": "cloudwatch_log_group_no_retention",
		"severity": "medium",
		"category": "energy",
		"resource_type": "aws_cloudwatch_log_group",
		"resource_id": group.name,
		"region": group.region,
		"message": sprintf("Log group '%v' never expires and already holds about %v GB, growing every month for data nothing reads.", [group.name, stored_gb]),
	}
}
