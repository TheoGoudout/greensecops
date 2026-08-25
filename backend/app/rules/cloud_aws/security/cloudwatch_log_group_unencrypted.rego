# METADATA
# title: Log groups are not encrypted with a KMS key
# description: One or more CloudWatch log groups have no KMS key, so its contents are encrypted only with keys AWS holds. Logs are rarely thought of as sensitive, which is exactly the problem — they routinely carry request paths with tokens in the query string, stack traces with connection strings, and enough identifiers to reconstruct who did what. A KMS key turns reading them into an auditable, revocable, separately-authorised action rather than something any principal with logs read access gets for free. Reported once for the account with a count and a sample rather than once per group.
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

# Aggregated to one finding for the account. Every Lambda creates a log group,
# so a modest account has hundreds, and one finding per group turned a real
# gap into a wall the reader scrolls past. The count is the signal; the sample
# is there so the finding is actionable without a second query.
_sample_limit := 5

_sample(names) := concat(", ", array.slice(sort(names), 0, _sample_limit))

_suffix(names) := "" if count(names) <= _sample_limit

_suffix(names) := sprintf(" and %v more", [count(names) - _sample_limit]) if count(names) > _sample_limit

_unencrypted := {group.name |
	some group in input.cloudwatch_log_groups
	group.name != ""
	object.get(group, "kms_key_id", null) == null
}

violations contains violation if {
	names := _unencrypted
	count(names) > 0

	violation := {
		"rule": "cloudwatch_log_group_unencrypted",
		"severity": "low",
		"category": "security",
		"resource_type": "aws_cloudwatch_log_group",
		"resource_id": "account",
		"message": sprintf("%v log group(s) have no KMS key, so reading them needs no separately-auditable key grant: %v%v.", [count(names), _sample(names), _suffix(names)]),
		"context": _sample(names),
		"discriminator": "account",
	}
}
