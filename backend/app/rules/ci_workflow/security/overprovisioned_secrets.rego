# METADATA
# title: Every secret handed to one step
# description: "An expression serialises the whole secrets context — toJSON(secrets) — or a reusable workflow is called with secrets: inherit. Either hands the callee every secret the repository has, including the ones it will never use, so a compromised action or a called workflow that logs its inputs leaks all of them rather than the one it was given. The blast radius of the step becomes the blast radius of the repository."
# custom:
#   severity: high
#   severity_weight: 2.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - run: ./deploy.sh
#               env:
#                 ALL_SECRETS: ${{ toJSON(secrets) }}
#     good: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - run: ./deploy.sh
#               env:
#                 DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}
#     fix: |
#       Name the secrets the step actually needs, one binding each. Where a reusable workflow needs several, declare them under secrets: by name in the call rather than inheriting — the explicit list is also the only record of what the called workflow is trusted with.
package greensecops.ci_workflow.security.overprovisioned_secrets

import rego.v1

_serialises_all_secrets(value) if {
	is_string(value)
	regex.match(`(?i)to_?json\s*\(\s*secrets\s*\)`, value)
}

# Any string anywhere in the job — env bindings, with: inputs, run scripts.
_job_serialises_all_secrets(job) if {
	regex.match(`(?i)to_?json\s*\(\s*secrets\s*\)`, json.marshal(job))
}

violations contains violation if {
	some job_name, job in input.jobs
	_job_serialises_all_secrets(job)

	violation := {
		"rule": "overprovisioned_secrets",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' serialises the entire secrets context with toJSON(secrets), handing every repository secret to a step that needs one of them. Bind the secrets the step uses, by name.", [job_name]),
		"context": "toJSON(secrets)",
		"discriminator": sprintf("%v:tojson", [job_name]),
	}
}

# Workflow-level env is worse still: every job, every step, every action.
violations contains violation if {
	some key, value in input.env
	_serialises_all_secrets(value)

	violation := {
		"rule": "overprovisioned_secrets",
		"severity": "high",
		"category": "security",
		"job": null,
		"message": sprintf("Workflow-level env var '%v' serialises the entire secrets context, so every step of every job runs with all of them in the environment — including third-party actions.", [key]),
		"context": "toJSON(secrets)",
		"discriminator": key,
	}
}
