# METADATA
# title: Long-lived cloud credentials instead of OIDC
# description: Workflow uses static cloud credentials (AWS_ACCESS_KEY_ID, etc.) stored as secrets instead of OIDC short-lived tokens.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           env:
#             AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
#             AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
#           steps:
#             - run: aws s3 sync dist/ s3://my-bucket
#     good: |
#       permissions:
#         id-token: write
#         contents: read
#       jobs:
#         deploy:
#           steps:
#             - uses: aws-actions/configure-aws-credentials@v4
#               with:
#                 role-to-assume: arn:aws:iam::123456789:role/github-actions
#                 aws-region: us-east-1
#             - run: aws s3 sync dist/ s3://my-bucket
#     fix: |
#       Configure OIDC federation between GitHub Actions and your cloud provider. Grant id-token: write permission and use the provider's official OIDC action instead of storing long-lived credentials.
package greensecops.security.oidc_not_used

import rego.v1

# Detects static cloud credentials stored as env vars instead of using
# OIDC-based short-lived tokens, which reduces the blast radius of leaks.

_static_cred_keys := {
	"AWS_ACCESS_KEY_ID",
	"AWS_SECRET_ACCESS_KEY",
	"AZURE_CREDENTIALS",
	"GCP_SA_KEY",
}

_check_env_for_static_creds(env, job_name) := {violation |
	some key in _static_cred_keys
	env[key]
	violation := {
		"rule": "oidc_not_used",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Static cloud credential '%v' found in env. Use OIDC (id-token: write + cloud provider OIDC action) instead of long-lived credentials.", [key]),
		"context": key,
		"discriminator": key,
	}
}

violations contains violation if {
	some v in _check_env_for_static_creds(input.env, null)
	violation := v
}

violations contains violation if {
	some job_name, job in input.jobs
	some v in _check_env_for_static_creds(job.env, job_name)
	violation := v
}
