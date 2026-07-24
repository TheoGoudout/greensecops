# METADATA
# title: Duplicated workflow blocks
# description: Identical job definitions appear across multiple workflow files without using reusable workflows (workflow_call trigger).
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

# Detects when 2 or more jobs share identical sets of 'uses' actions in their
# steps, suggesting the duplicated logic should be extracted into a reusable
# workflow or composite action.

_step_uses_list(job) := [action |
	some step in job.steps
	action := step.uses
	action != null
]

_jobs_with_uses_list(uses_list) := {job_name |
	some job_name, job in input.jobs
	_step_uses_list(job) == uses_list
}

violations contains violation if {
	some job_name, job in input.jobs
	uses_list := _step_uses_list(job)
	count(uses_list) > 0
	matching := _jobs_with_uses_list(uses_list)
	count(matching) >= 2
	violation := {
		"rule": "no_reusable_workflow",
		"severity": "info",
		"category": "maintainability",
		"job": job_name,
		"message": sprintf("Job '%v' has identical step actions to %v other job(s). Extract shared logic into a reusable workflow or composite action.", [job_name, count(matching) - 1]),
		"context": null,
	}
}
