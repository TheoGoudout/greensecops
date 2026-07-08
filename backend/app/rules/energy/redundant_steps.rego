# METADATA
# title: Redundant steps across jobs
# description: Identical setup steps (checkout, dependency install) are duplicated across jobs without using reusable workflows or job outputs.
# custom:
#   severity: medium
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         test:
#           steps:
#             - uses: actions/checkout@v4
#             - uses: actions/setup-node@v4
#             - run: npm test
#         lint:
#           steps:
#             - uses: actions/checkout@v4
#             - uses: actions/setup-node@v4
#             - run: npm run lint
#         build:
#           steps:
#             - uses: actions/checkout@v4
#             - uses: actions/setup-node@v4
#             - run: npm run build
#     good: |
#       jobs:
#         test:
#           uses: ./.github/workflows/reusable-node.yml
#           with: {script: npm test}
#         lint:
#           uses: ./.github/workflows/reusable-node.yml
#           with: {script: npm run lint}
#         build:
#           uses: ./.github/workflows/reusable-node.yml
#           with: {script: npm run build}
#     fix: |
#       Extract shared setup into a reusable workflow or composite action so the checkout and setup steps run once rather than being duplicated across jobs.
package greensecops.energy.redundant_steps

import rego.v1

# Detects when the same action (e.g. actions/checkout) is used in more than 2 jobs,
# which may indicate redundant work that could be consolidated or cached.

_action_base(uses) := base if {
	parts := split(uses, "@")
	base := parts[0]
}

_jobs_using_action(action_base) := {job_name |
	some job_name, job in input.jobs
	some step in job.steps
	step.uses
	_action_base(step.uses) == action_base
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	uses != null
	base := _action_base(uses)
	jobs_using := _jobs_using_action(base)
	count(jobs_using) > 2
	violation := {
		"rule": "redundant_steps",
		"severity": "low",
		"category": "energy",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Action '%v' is used in %v jobs. Consider consolidating or sharing results to avoid redundant work.", [base, count(jobs_using)]),
		"context": uses,
	}
}
