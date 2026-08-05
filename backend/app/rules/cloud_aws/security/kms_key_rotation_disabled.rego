# METADATA
# title: Customer-managed KMS key does not rotate
# description: A customer-managed KMS key has automatic rotation switched off. Rotation here is cheap in a way it is not elsewhere — AWS keeps every previous key version and picks the right one to decrypt with, so nothing needs re-encrypting and no application notices. What it buys is a bound on how much data any single key version protects, which is what limits the blast radius if key material is ever compromised. Given the cost is one flag and no downtime, leaving it off is rarely a decision anyone made deliberately.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws kms create-key --description "application data"
#     good: |
#       KEY=$(aws kms create-key --description "application data" \
#         --query KeyMetadata.KeyId --output text)
#       aws kms enable-key-rotation --key-id "$KEY"
#     fix: |
#       Run `aws kms enable-key-rotation --key-id <id>`. Old versions are retained automatically, so existing ciphertext keeps decrypting and there is nothing to migrate.
package greensecops.cloud_aws.security.kms_key_rotation_disabled

import rego.v1

violations contains violation if {
	# The collector already filters to KeyManager == CUSTOMER, so every key
	# here is one whose rotation the account actually controls. AWS-managed
	# keys rotate on their own schedule and cannot be configured, which is why
	# reporting them would be noise nobody can act on.
	some key in input.kms_keys

	key.rotation_enabled == false

	violation := {
		"rule": "kms_key_rotation_disabled",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_kms_key",
		"resource_id": key.id,
		"region": key.region,
		"message": sprintf("KMS key '%v' does not rotate automatically, so one key version protects everything ever encrypted under it.", [key.id]),
	}
}
