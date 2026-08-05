# METADATA
# title: EBS volume is encrypted with the AWS-managed key
# description: An encrypted EBS volume uses the AWS-managed default key rather than a customer-managed one. The data is encrypted either way, so this is not about the cipher — it is about who controls the key. You cannot attach a key policy to the AWS-managed key, cannot audit its use as a separate grant, cannot rotate it on your schedule, and cannot revoke it to make a snapshot unreadable. A customer-managed key turns all four of those from impossible into a policy change, which is what makes it worth the small extra cost.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ec2 create-volume --size 100 --availability-zone eu-west-1a --encrypted
#     good: |
#       aws ec2 create-volume --size 100 --availability-zone eu-west-1a --encrypted \
#         --kms-key-id arn:aws:kms:eu-west-1:123456789012:key/abc-123
#     fix: |
#       Set a customer-managed key as the EBS default for the region so new volumes pick it up automatically. Existing volumes cannot be re-keyed in place — snapshot, copy the snapshot with the new key, and restore.
package greensecops.cloud_aws.security.ebs_uses_aws_managed_key

import rego.v1

# `input.kms_keys` is the *customer-managed* set — the collector drops
# everything whose KeyManager is not CUSTOMER — so a key ARN matching none of
# them is the AWS-managed default. The resource carries a full ARN and the key
# entry a bare UUID, hence the suffix match.
_is_customer_managed(key_arn) if {
	some key in input.kms_keys
	endswith(key_arn, key.id)
}

violations contains violation if {
	some volume in input.ebs_volumes

	# An empty key list means either "no customer keys exist" or "no
	# kms:ListKeys permission", and those are indistinguishable. Firing on the
	# second would let a permission gap manufacture a finding against every
	# encrypted resource in the account, which is the one thing cloud rules
	# here must never do. The cost is a missed finding on an account that
	# genuinely has no customer keys — the same trade cloudtrail_absent makes.
	count(input.kms_keys) > 0

	volume.encrypted == true
	key_arn := volume.kms_key_id
	is_string(key_arn)
	not _is_customer_managed(key_arn)

	violation := {
		"rule": "ebs_uses_aws_managed_key",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_ebs_volume",
		"resource_id": volume.id,
		"region": volume.region,
		"message": sprintf("Volume '%v' is encrypted with the AWS-managed key, so its key policy, rotation and revocation are not yours to set.", [volume.id]),
	}
}
