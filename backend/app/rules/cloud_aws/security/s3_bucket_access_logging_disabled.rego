# METADATA
# title: Buckets have no access logging
# description: One or more S3 buckets do not log the requests made against them. Without server access logs there is no record of who read an object or when, so a data-exposure question after the fact — did anyone actually download this — has no answer at all, only a shrug. That answer is what determines whether an incident is a notification obligation or a near miss, which makes the logging decision worth far more than the pennies it costs. Reported once for the account with a count and a sample rather than once per bucket.
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

# Aggregated to one finding for the account. Every Lambda creates a log group,
# so a modest account has hundreds, and one finding per group turned a real
# gap into a wall the reader scrolls past. The count is the signal; the sample
# is there so the finding is actionable without a second query.
_sample_limit := 5

_sample(names) := concat(", ", array.slice(sort(names), 0, _sample_limit))

_suffix(names) := "" if count(names) <= _sample_limit

_suffix(names) := sprintf(" and %v more", [count(names) - _sample_limit]) if count(names) > _sample_limit

_unlogged := {bucket.name |
	some bucket in input.s3_buckets
	bucket.logging_enabled == false
}

violations contains violation if {
	names := _unlogged
	count(names) > 0

	violation := {
		"rule": "s3_bucket_access_logging_disabled",
		"severity": "low",
		"category": "security",
		"resource_type": "aws_s3_bucket",
		"resource_id": "account",
		"region": "global",
		"message": sprintf("%v bucket(s) have no access logging, so there is no record of who read from them: %v%v.", [count(names), _sample(names), _suffix(names)]),
		"context": _sample(names),
		"discriminator": "account",
	}
}
