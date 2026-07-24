# METADATA
# title: Unattached EBS volume
# description: A live EBS volume is not attached to any instance, and is very likely a forgotten leftover still incurring storage cost with no owner tracking whether it's safe to delete.
# custom:
#   severity: low
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ec2 describe-volumes --volume-ids vol-0123
#       # Attachments: []
#     good: |
#       aws ec2 describe-volumes --volume-ids vol-0123
#       # Attachments: [{"InstanceId": "i-0123"}]
#     fix: |
#       Snapshot the volume if it might still be needed, then delete it; otherwise delete it directly.
package greensecops.cloud_aws.maintainability.ebs_volume_unattached

import rego.v1

violations contains violation if {
	some vol in input.ebs_volumes
	not vol.attached
	violation := {
		"rule": "ebs_volume_unattached",
		"severity": "low",
		"category": "maintainability",
		"resource_type": "aws_ebs_volume",
		"resource_id": vol.id,
		"region": vol.region,
		"message": sprintf("EBS volume '%v' is not attached to any instance.", [vol.id]),
	}
}
