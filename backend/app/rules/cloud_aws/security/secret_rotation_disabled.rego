# METADATA
# title: Secrets Manager secret does not rotate
# description: A secret in Secrets Manager has rotation switched off, so its value is whatever it was on the day it was created. Storing a credential in Secrets Manager rather than a config file is a real improvement in how it is *distributed*, but on its own it changes nothing about how long a leaked copy stays valid — and a credential that never changes is one every past holder still has. Rotation is the part that bounds the damage, and it is the part most often left for later.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws secretsmanager create-secret --name prod/db/password \
#         --secret-string "$GENERATED"
#     good: |
#       aws secretsmanager rotate-secret --secret-id prod/db/password \
#         --rotation-lambda-arn "$ROTATOR" \
#         --rotation-rules AutomaticallyAfterDays=30
#     fix: |
#       Attach a rotation function — AWS publishes ready-made ones for RDS, Redshift and DocumentDB — and set an interval. For a secret nothing can rotate automatically, such as a third-party API key, the honest options are a calendar reminder or moving to a provider that issues short-lived credentials.
package greensecops.cloud_aws.security.secret_rotation_disabled

import rego.v1

violations contains violation if {
	some secret in input.secrets

	secret.rotation_enabled == false

	violation := {
		"rule": "secret_rotation_disabled",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_secretsmanager_secret",
		"resource_id": secret.name,
		"region": secret.region,
		"message": sprintf("Secret '%v' does not rotate, so its value is unchanged since creation and every past holder still has a working copy.", [secret.name]),
	}
}
