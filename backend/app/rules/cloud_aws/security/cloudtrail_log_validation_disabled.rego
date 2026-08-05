# METADATA
# title: CloudTrail log file validation is off
# description: A CloudTrail trail does not write digest files, so there is no way to prove afterwards that the log was not edited or that no file was quietly deleted. That matters exactly once, during an incident, and by then it cannot be turned on retroactively — validation only covers files written after it was enabled. The whole value of an audit log rests on it being tamper-evident, and an attacker with write access to the bucket is precisely the person who would edit it.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws cloudtrail create-trail --name audit --s3-bucket-name audit-logs
#     good: |
#       aws cloudtrail create-trail --name audit --s3-bucket-name audit-logs \
#         --enable-log-file-validation
#     fix: |
#       Run `aws cloudtrail update-trail --name <trail> --enable-log-file-validation`, then verify with `aws cloudtrail validate-logs`. Pair it with object lock or a versioned, cross-account bucket so a deletion is as detectable as an edit.
package greensecops.cloud_aws.security.cloudtrail_log_validation_disabled

import rego.v1

violations contains violation if {
	some trail in input.cloudtrail_trails

	trail.log_file_validation_enabled == false

	violation := {
		"rule": "cloudtrail_log_validation_disabled",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_cloudtrail",
		"resource_id": trail.name,
		"region": trail.region,
		"message": sprintf("Trail '%v' writes no digest files, so its log cannot be shown to be unedited after the fact.", [trail.name]),
	}
}
