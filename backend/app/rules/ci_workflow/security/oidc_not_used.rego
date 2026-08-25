# METADATA
# title: Long-lived cloud credentials instead of OIDC
# description: Workflow uses static cloud credentials (AWS_ACCESS_KEY_ID, etc.) stored as secrets instead of OIDC short-lived tokens.
# custom:
#   severity: high
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
#             - uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e071d42e0343502 # v4.0.2
#               with:
#                 role-to-assume: arn:aws:iam::123456789:role/github-actions
#                 aws-region: us-east-1
#             - run: aws s3 sync dist/ s3://my-bucket
#     fix: |
#       Configure OIDC federation between GitHub Actions and your cloud provider. Grant id-token: write permission and use the provider's official OIDC action instead of storing long-lived credentials.
package greensecops.ci_workflow.security.oidc_not_used

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

# The dominant form in the wild is not an env var at all — it is the cloud
# login action taking the key as an input. This rule read only `env:`, so the
# configuration it exists to replace was the one shape it could not see.
_static_cred_inputs := {
	"aws-access-key-id",
	"aws-secret-access-key",
	"creds",
	"credentials",
	"credentials_json",
	"service_account_key",
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	some input_name, value in step["with"]
	input_name in _static_cred_inputs
	is_string(value)

	violation := {
		"rule": "oidc_not_used",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step": object.get(step, "uses", null),
		"step_index": step_index,
		"line_start": object.get(step, "__start_line__", null),
		"line_end": object.get(step, "__end_line__", null),
		"message": sprintf("Job '%v' passes a long-lived credential to %v through '%v'. Use OIDC instead — grant id-token: write and give the action a role to assume, so the run gets a short-lived token it cannot leak past its own duration.", [job_name, object.get(step, "uses", "an action"), input_name]),
		"context": input_name,
		"discriminator": sprintf("%v:%v:%v", [job_name, step_index, input_name]),
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
