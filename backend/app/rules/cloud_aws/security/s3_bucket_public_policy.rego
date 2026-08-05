# METADATA
# title: Bucket policy grants access to everyone
# description: An S3 bucket policy has an Allow statement whose principal is the wildcard, granting the action to every AWS account and every anonymous caller on the internet. This is a different exposure from a public ACL — the public access block settings that the s3_public_access_block_disabled rule checks can be fully on and a policy like this still applies, because BlockPublicPolicy only rejects policies at write time if it was enabled before the policy was put. A statement carrying a Condition is not reported, since conditions are the supported way to scope a wildcard principal to a VPC endpoint, an organization or a source IP range.
# custom:
#   severity: critical
#   detection: cloud_posture
#   examples:
#     bad: |
#       {
#         "Effect": "Allow",
#         "Principal": "*",
#         "Action": "s3:GetObject",
#         "Resource": "arn:aws:s3:::assets/*"
#       }
#     good: |
#       {
#         "Effect": "Allow",
#         "Principal": {"AWS": "arn:aws:iam::123456789012:role/reader"},
#         "Action": "s3:GetObject",
#         "Resource": "arn:aws:s3:::assets/*"
#       }
#     fix: |
#       Name the accounts or roles that need the access. If the bucket really is meant to serve the public, front it with CloudFront and grant the origin access identity instead, so the objects are reachable only through a distribution you can rate-limit and log.
package greensecops.cloud_aws.security.s3_bucket_public_policy

import rego.v1

_public_principal(statement) if "*" in statement.principals

_public_principal(statement) if "arn:aws:iam::*:root" in statement.principals

violations contains violation if {
	some bucket in input.s3_buckets
	some index, statement in bucket.policy_statements

	statement.effect == "Allow"
	_public_principal(statement)

	# A condition is how a wildcard principal is legitimately scoped — to a VPC
	# endpoint, an organization ID or a source IP range. Reporting those would
	# make the rule fire on the recommended pattern.
	not statement.has_condition

	violation := {
		"rule": "s3_bucket_public_policy",
		"severity": "critical",
		"category": "security",
		"resource_type": "aws_s3_bucket",
		"resource_id": bucket.name,
		"region": "global",
		"message": sprintf("Bucket '%v' has a policy statement allowing %v to any principal with no condition attached.", [bucket.name, concat(", ", statement.actions)]),
		"discriminator": sprintf("statement-%v", [index]),
	}
}
