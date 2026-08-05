# METADATA
# title: IAM access key has gone unused for months
# description: A long-lived IAM access key has not been used in over 90 days. An unused key is the worst kind of credential — it carries the same authority as an active one, but nobody would notice it being used, because there is no normal traffic to compare against. It is also the easiest thing in this whole report to fix, since by definition nothing depends on it. Deleting it is not a mitigation, it is a removal — the credential stops existing.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       # aws iam get-credential-report
#       # deploy,...,access_key_1_last_used_date=2024-02-11  (nothing since)
#     good: |
#       aws iam delete-access-key --user-name deploy --access-key-id AKIA...
#     fix: |
#       Deactivate the key first — that reverses in one command if something does turn out to use it — and delete it after a week of nothing breaking. If the key belongs to a decommissioned integration, delete the user too rather than leaving an empty identity behind.
package greensecops.cloud_aws.security.iam_access_key_unused

import rego.v1

_max_unused_days := 90

violations contains violation if {
	some user in input.iam_users

	unused := user.access_key_unused_days

	# Null covers both "no credential report" and "key never used at all"; the
	# collector reports a number only when it measured one.
	is_number(unused)
	unused > _max_unused_days

	violation := {
		"rule": "iam_access_key_unused",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_iam_user",
		"resource_id": user.name,
		"region": "global",
		"message": sprintf("User '%v' has an access key unused for %v days. Nothing depends on it, and its use would look like normal traffic to nobody.", [user.name, unused]),
	}
}
