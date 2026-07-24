# METADATA
# title: S3 bucket without versioning
# description: A live S3 bucket has no versioning enabled, so an accidental overwrite or delete of an object can't be recovered.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws s3api get-bucket-versioning --bucket my-bucket
#       # {} (no Status)
#     good: |
#       aws s3api put-bucket-versioning --bucket my-bucket --versioning-configuration Status=Enabled
#     fix: |
#       Enable versioning on the bucket.
package greensecops.cloud_aws.reliability.s3_bucket_missing_versioning

import rego.v1

violations contains violation if {
	some bucket in input.s3_buckets
	not bucket.versioning_enabled
	violation := {
		"rule": "s3_bucket_missing_versioning",
		"severity": "medium",
		"category": "reliability",
		"resource_type": "aws_s3_bucket",
		"resource_id": bucket.name,
		"message": sprintf("S3 bucket '%v' does not have versioning enabled.", [bucket.name]),
	}
}
