# METADATA
# title: S3 bucket without default encryption
# description: A live S3 bucket has no server-side encryption configuration, leaving objects stored unencrypted at rest unless a caller opts in per-object.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws s3api get-bucket-encryption --bucket my-bucket
#       # ServerSideEncryptionConfigurationNotFoundError
#     good: |
#       aws s3api put-bucket-encryption --bucket my-bucket \
#         --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
#     fix: |
#       Enable default encryption (SSE-S3 or SSE-KMS) on the bucket.
package greensecops.cloud_aws.security.s3_bucket_unencrypted

import rego.v1

violations contains violation if {
	some bucket in input.s3_buckets
	not bucket.encrypted
	violation := {
		"rule": "s3_bucket_unencrypted",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_s3_bucket",
		"resource_id": bucket.name,
		"message": sprintf("S3 bucket '%v' has no default encryption configuration.", [bucket.name]),
	}
}
