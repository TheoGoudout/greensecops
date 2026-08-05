# METADATA
# title: IAM access key has not been rotated in a year
# description: A long-lived IAM access key is older than 365 days. Static keys do not expire on their own, and every day one exists is another day it might have been copied into a laptop backup, a CI log, a Slack message or a git history — none of which you can audit after the fact. Rotation does not stop a key leaking, but it bounds how long a leaked key stays useful, which is the only property you actually control. A key whose age cannot be read is not reported, because a missing credential report is not evidence of an old key.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       # aws iam list-access-keys --user-name deploy
#       # CreateDate: 2023-01-04  (over a year ago, still active)
#     good: |
#       # No static key at all — the deploy pipeline assumes a role via OIDC:
#       aws iam create-role --role-name deploy \
#         --assume-role-policy-document file://github-oidc-trust.json
#     fix: |
#       Replace the key rather than rotating it where you can — a CI pipeline should assume a role through OIDC and a human should use identity-centre credentials, neither of which involves a static key. Where a static key is genuinely required, rotate it on a schedule and delete the previous one once the new one is in use.
package greensecops.cloud_aws.security.iam_access_key_too_old

import rego.v1

_max_key_age_days := 365

violations contains violation if {
	some user in input.iam_users

	age := user.access_key_age_days

	# The collector reports null when the credential report could not be read,
	# and a missing report is not evidence of an old key.
	is_number(age)
	age > _max_key_age_days

	violation := {
		"rule": "iam_access_key_too_old",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_iam_user",
		"resource_id": user.name,
		"region": "global",
		"message": sprintf("User '%v' has an access key %v days old, past the %v-day rotation bound — a key that leaked at any point in that window is still valid.", [user.name, age, _max_key_age_days]),
	}
}
