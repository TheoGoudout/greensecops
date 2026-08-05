# METADATA
# title: Bucket has no access logging
# description: An S3 bucket does not log the requests made against it. Without server access logs there is no record of who read an object or when, so a data-exposure question after the fact — did anyone actually download this — has no answer at all, only a shrug. That answer is what determines whether an incident is a notification obligation or a near miss, which makes the logging decision worth far more than the pennies it costs.
# custom:
#   severity: low
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws s3api create-bucket --bucket customer-exports --region eu-west-1
#     good: |
#       aws s3api put-bucket-logging --bucket customer-exports \
#         --bucket-logging-status '{"LoggingEnabled":{"TargetBucket":"audit-logs","TargetPrefix":"customer-exports/"}}'
#     fix: |
#       Point the bucket at a dedicated log bucket in the same region. Keep the target separate from the source — logging a bucket into itself creates a feedback loop that grows without bound — and apply a lifecycle rule to the log bucket so the records expire on a schedule you chose.
package greensecops.cloud_aws.security.s3_bucket_access_logging_disabled

import rego.v1

violations contains violation if {
	some bucket in input.s3_buckets

	bucket.logging_enabled == false

	violation := {
		"rule": "s3_bucket_access_logging_disabled",
		"severity": "low",
		"category": "security",
		"resource_type": "aws_s3_bucket",
		"resource_id": bucket.name,
		"region": "global",
		"message": sprintf("Bucket '%v' has no access logging, so there is no record of who read from it.", [bucket.name]),
	}
}
