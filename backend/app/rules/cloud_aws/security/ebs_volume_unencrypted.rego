# METADATA
# title: EBS volume not encrypted
# description: A live EBS volume has Encrypted set to false, leaving its data at rest unencrypted.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ec2 describe-volumes --volume-ids vol-0123
#       # Encrypted: false
#     good: |
#       aws ec2 describe-volumes --volume-ids vol-0123
#       # Encrypted: true
#     fix: |
#       Encryption can't be enabled on an existing volume — snapshot it, copy the snapshot with encryption enabled, and create a new volume from the encrypted copy.
package greensecops.cloud_aws.security.ebs_volume_unencrypted

import rego.v1

violations contains violation if {
	some vol in input.ebs_volumes
	not vol.encrypted
	violation := {
		"rule": "ebs_volume_unencrypted",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_ebs_volume",
		"resource_id": vol.id,
		"region": vol.region,
		"message": sprintf("EBS volume '%v' is not encrypted.", [vol.id]),
	}
}
