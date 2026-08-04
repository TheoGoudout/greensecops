# METADATA
# title: CloudWatch log group keeps logs forever
# description: An aws_cloudwatch_log_group sets no retention_in_days, which means "never expire" — the default. The group then accumulates every log line the service has ever written, billed per GB per month for as long as the account exists, and the cost curve is invisible because no single deploy makes it worse. It is also a compliance liability in the other direction, since data a retention policy says should be gone is still there.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_cloudwatch_log_group" "api" {
#         name = "/aws/lambda/api"
#       }
#     good: |
#       resource "aws_cloudwatch_log_group" "api" {
#         name              = "/aws/lambda/api"
#         retention_in_days = 30
#       }
#     fix: |
#       Set retention_in_days to what the logs are actually used for — 30 days covers most debugging, and anything needed longer belongs in S3 with a lifecycle policy, which is far cheaper per GB than CloudWatch Logs.
package greensecops.iac_terraform.reliability.cloudwatch_log_group_no_retention

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, group in res.aws_cloudwatch_log_group

	# `0` is how the provider spells "never expire" explicitly, and is the same
	# outcome as omitting the attribute.
	not _has_retention(group)

	violation := {
		"rule": "cloudwatch_log_group_no_retention",
		"severity": "medium",
		"category": "reliability",
		"resource_address": sprintf("aws_cloudwatch_log_group.%v", [name]),
		"file_path": object.get(group, "__tf_file", ""),
		"line_start": object.get(group, "__start_line__", null),
		"line_end": object.get(group, "__end_line__", null),
		"message": sprintf("Log group '%v' has no retention_in_days, so logs are kept forever and billed forever.", [name]),
	}
}

_has_retention(group) if {
	days := group.retention_in_days
	is_number(days)
	days > 0
}

# hcl2 does not evaluate expressions, so `retention_in_days =
# var.log_retention_days` arrives as the string "${var.log_retention_days}".
# The value is unknowable here, but the attribute was deliberately set — and a
# module that takes its retention as an input is the well-configured case, not
# the one this rule is looking for. Treating a reference as unset would report
# every parameterised module, which is most real Terraform.
_has_retention(group) if {
	days := group.retention_in_days
	is_string(days)
	trim_space(days) != ""
}
