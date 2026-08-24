# METADATA
# title: IAM user without MFA
# description: "A live IAM user with console access has no MFA device registered, so a leaked password alone is sufficient to authenticate as them. Users without console access are excluded: they have no password, so there is nothing for a second factor to protect — an access-key-only principal is covered by the key age and least-privilege rules instead."
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws iam list-mfa-devices --user-name alice
#       # MFADevices: []
#     good: |
#       aws iam list-mfa-devices --user-name alice
#       # MFADevices: [{"SerialNumber": "arn:aws:iam::...:mfa/alice"}]
#     fix: |
#       Require the user to register a virtual or hardware MFA device, and enforce it via an IAM policy condition.
package greensecops.cloud_aws.security.iam_user_no_mfa

import rego.v1

# MFA protects a password. A user with no console access has no password to
# protect — it authenticates with an access key, for which the controls are
# rotation and least privilege, both of which other rules already check. The
# collector has reported `console_access` all along and this rule ignored it,
# so every CI and service principal in the account was a high-severity finding.
violations contains violation if {
	some user in input.iam_users
	user.console_access == true
	not user.mfa_enabled
	violation := {
		"rule": "iam_user_no_mfa",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_iam_user",
		"resource_id": user.name,
		"message": sprintf("IAM user '%v' has no MFA device registered.", [user.name]),
	}
}
