# METADATA
# title: CloudTrail trail not logging
# description: A live CloudTrail trail exists but is not actively logging, leaving API activity in the account unrecorded and unavailable for incident investigation.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws cloudtrail get-trail-status --name org-trail
#       # IsLogging: false
#     good: |
#       aws cloudtrail start-logging --name org-trail
#     fix: |
#       Start logging on the trail, and alert if it stops again.
package greensecops.cloud_aws.reliability.cloudtrail_logging_disabled

import rego.v1

violations contains violation if {
	some trail in input.cloudtrail_trails
	not trail.is_logging
	violation := {
		"rule": "cloudtrail_logging_disabled",
		"severity": "high",
		"category": "reliability",
		"resource_type": "aws_cloudtrail_trail",
		"resource_id": trail.name,
		"region": trail.region,
		"message": sprintf("CloudTrail trail '%v' is not currently logging.", [trail.name]),
	}
}
