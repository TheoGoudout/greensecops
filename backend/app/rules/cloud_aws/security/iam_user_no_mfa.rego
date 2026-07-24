# METADATA
# title: IAM user without MFA
# description: A live IAM user has no MFA device registered, so a leaked password alone is sufficient to authenticate as them.
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

violations contains violation if {
	some user in input.iam_users
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
