# METADATA
# title: Two jobs with identical steps
# description: "Two or more jobs in the workflow have exactly the same steps — the same actions in the same order with the same run commands — so the same logic is maintained in more than one place and a change has to be made in each. Comparison includes the run scripts: jobs that merely share a checkout and a language setup are not duplicates, and treating them as such reported every fan-out workflow in existence."
# custom:
#   severity: info
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         test-v1:
#           steps:
#             - uses: actions/checkout@v4
#             - uses: actions/setup-node@v4
#             - run: npm test
#         test-v2:
#           steps:
#             - uses: actions/checkout@v4
#             - uses: actions/setup-node@v4
#             - run: npm test
#     good: |
#       jobs:
#         test-v1:
#           uses: ./.github/workflows/reusable-test.yml
#           with: {node-version: 18}
#         test-v2:
#           uses: ./.github/workflows/reusable-test.yml
#           with: {node-version: 20}
#     fix: |
#       Extract the shared job definition into a reusable workflow (on: workflow_call:) or a composite action, then call it with uses:.
package greensecops.ci_workflow.maintainability.no_reusable_workflow

import rego.v1

# Two jobs are duplicates when their whole step lists match, `run:` scripts
# included. Comparing only the `uses:` values — which is what this did — made
# every pair of jobs that checked out and set up a language look identical
# however differently they then behaved. On this repository that reported five
# jobs which lint Ansible, check Cloudflare, check Coolify, check Terraform and
# check versions as duplicated logic.
_step_signature(step) := sprintf("uses:%v", [step.uses]) if is_string(step.uses)

_step_signature(step) := sprintf("run:%v", [trim_space(step.run)]) if {
	not step.uses
	is_string(step.run)
}

_job_signature(job) := [_step_signature(step) | some step in job.steps]

_jobs_with_signature(signature) := {job_name |
	some job_name, job in input.jobs
	_job_signature(job) == signature
}

violations contains violation if {
	some job_name, job in input.jobs
	signature := _job_signature(job)

	# One shared step is a coincidence — every job checks out.
	count(signature) > 1
	matching := _jobs_with_signature(signature)
	count(matching) >= 2
	violation := {
		"rule": "no_reusable_workflow",
		"severity": "info",
		"category": "maintainability",
		"job": job_name,
		"message": sprintf("Job '%v' has the same steps as %v other job(s), commands included. Extract them into a reusable workflow or a composite action.", [job_name, count(matching) - 1]),
		"context": null,
		"discriminator": job_name,
	}
}
