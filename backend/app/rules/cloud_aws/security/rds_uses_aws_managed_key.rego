# METADATA
# title: RDS instance is encrypted with the AWS-managed key
# description: An encrypted RDS instance uses the AWS-managed default key rather than a customer-managed one. As with EBS the data is encrypted either way, and what is missing is control — no key policy of your own, no separate grant to audit, no rotation on your schedule, and no way to revoke access to the automated backups and snapshots that inherit the instance's key. For a database that is usually the most sensitive store in the account, that control is worth more than it is for a volume.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws rds create-db-instance --db-instance-identifier prod \
#         --engine postgres --storage-encrypted
#     good: |
#       aws rds create-db-instance --db-instance-identifier prod \
#         --engine postgres --storage-encrypted \
#         --kms-key-id arn:aws:kms:eu-west-1:123456789012:key/abc-123
#     fix: |
#       An instance's key cannot be changed in place — snapshot it, copy the snapshot specifying the customer-managed key, and restore from the copy. Do it during a planned window, and remember the old snapshots keep the old key until they are deleted.
package greensecops.cloud_aws.security.rds_uses_aws_managed_key

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
	some db in input.rds_instances

	# An empty key list means either "no customer keys exist" or "no
	# kms:ListKeys permission", and those are indistinguishable. Firing on the
	# second would let a permission gap manufacture a finding against every
	# encrypted resource in the account, which is the one thing cloud rules
	# here must never do. The cost is a missed finding on an account that
	# genuinely has no customer keys — the same trade cloudtrail_absent makes.
	count(input.kms_keys) > 0

	db.storage_encrypted == true
	key_arn := db.kms_key_id
	is_string(key_arn)
	not _is_customer_managed(key_arn)

	violation := {
		"rule": "rds_uses_aws_managed_key",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_db_instance",
		"resource_id": db.id,
		"region": db.region,
		"message": sprintf("Database '%v' is encrypted with the AWS-managed key, so neither it nor the snapshots inheriting that key can be revoked by policy you control.", [db.id]),
	}
}
