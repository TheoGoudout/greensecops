# METADATA
# title: Log group is not encrypted with a KMS key
# description: A CloudWatch log group has no KMS key, so its contents are encrypted only with keys AWS holds. Logs are rarely thought of as sensitive, which is exactly the problem — they routinely carry request paths with tokens in the query string, stack traces with connection strings, and enough identifiers to reconstruct who did what. A KMS key turns reading them into an auditable, revocable, separately-authorised action rather than something any principal with logs read access gets for free.
# custom:
#   severity: low
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws logs create-log-group --log-group-name /aws/lambda/checkout
#     good: |
#       aws logs create-log-group --log-group-name /aws/lambda/checkout
#       aws logs associate-kms-key --log-group-name /aws/lambda/checkout \
#         --kms-key-id arn:aws:kms:eu-west-1:123456789012:key/abc-123
#     fix: |
#       Associate a customer-managed key with the group. The key policy needs to allow the CloudWatch Logs service principal in that region to encrypt, or the association is rejected — that grant is on the key, not on the group.
package greensecops.cloud_aws.security.cloudwatch_log_group_unencrypted

import rego.v1

violations contains violation if {
	some group in input.cloudwatch_log_groups

	# The group has to be present for this to mean anything — a rule keyed on a
	# missing field is vacuously true for every document in every engine.
	group.name != ""
	object.get(group, "kms_key_id", null) == null

	violation := {
		"rule": "cloudwatch_log_group_unencrypted",
		"severity": "low",
		"category": "security",
		"resource_type": "aws_cloudwatch_log_group",
		"resource_id": group.name,
		"region": group.region,
		"message": sprintf("Log group '%v' has no KMS key, so reading it needs no separately-auditable key grant.", [group.name]),
	}
}
