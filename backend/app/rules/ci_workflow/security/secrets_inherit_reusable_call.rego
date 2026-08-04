# METADATA
# title: Reusable workflow called with secrets inherit
# description: A job calls a reusable workflow with secrets inherit, which passes every secret the calling repository has rather than the ones the callee declares. The called workflow's own inputs then say nothing about what it can reach, so reviewing the call tells you nothing about the exposure — and adding an unrelated secret to the repository silently widens it. It matters most when the callee lives in another repository, where its contents can change without a review here.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           uses: my-org/workflows/.github/workflows/deploy.yml@main
#           secrets: inherit
#     good: |
#       jobs:
#         deploy:
#           uses: my-org/workflows/.github/workflows/deploy.yml@a81bbbf8298c0fa03ea29cdc473d45769f953675
#           secrets:
#             DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}
#     fix: |
#       Name the secrets the called workflow needs. The call site then documents the exposure, and a secret added later for something else is not swept in.
package greensecops.ci_workflow.security.secrets_inherit_reusable_call

import rego.v1

violations contains violation if {
	some job_name, job in input.jobs
	is_string(job.uses)
	secrets := job.secrets
	is_string(secrets)
	lower(trim_space(secrets)) == "inherit"

	violation := {
		"rule": "secrets_inherit_reusable_call",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"step": job.uses,
		"message": sprintf("Job '%v' passes every repository secret to %v rather than the ones it declares, so the call site does not document what the workflow can reach.", [job_name, job.uses]),
		"context": "secrets: inherit",
		"discriminator": job_name,
	}
}
