# METADATA
# title: S3 bucket without a full public access block
# description: A live S3 bucket does not have all four Block Public Access settings (BlockPublicAcls, BlockPublicPolicy, IgnorePublicAcls, RestrictPublicBuckets) enabled, leaving a path for the bucket or its objects to become publicly accessible.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws s3api put-public-access-block --bucket my-bucket \
#         --public-access-block-configuration BlockPublicAcls=false,BlockPublicPolicy=true,IgnorePublicAcls=false,RestrictPublicBuckets=true
#     good: |
#       aws s3api put-public-access-block --bucket my-bucket \
#         --public-access-block-configuration BlockPublicAcls=true,BlockPublicPolicy=true,IgnorePublicAcls=true,RestrictPublicBuckets=true
#     fix: |
#       Enable all four Block Public Access settings unless the bucket has a deliberate, narrowly-scoped public use case.
package greensecops.cloud_aws.security.s3_public_access_block_disabled

import rego.v1

violations contains violation if {
	some bucket in input.s3_buckets
	not all_block_public_access_enabled(bucket)
	violation := {
		"rule": "s3_public_access_block_disabled",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_s3_bucket",
		"resource_id": bucket.name,
		"message": sprintf("S3 bucket '%v' does not have all Block Public Access settings enabled.", [bucket.name]),
	}
}

all_block_public_access_enabled(bucket) if {
	bucket.block_public_acls
	bucket.block_public_policy
	bucket.ignore_public_acls
	bucket.restrict_public_buckets
}
