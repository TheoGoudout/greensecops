# METADATA
# title: continue-on-error masking failures
# description: "continue-on-error: true is set on a step that is not explicitly intended to be optional. This can silently hide real failures."
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         ci:
#           steps:
#             - name: Run tests
#               run: npm test
#               continue-on-error: true
#     good: |
#       jobs:
#         ci:
#           steps:
#             - name: Run tests
#               run: npm test
#     fix: |
#       Remove continue-on-error: true from non-optional steps. If the step is genuinely optional (e.g. coverage upload), add a comment explaining why.
package greensecops.ci_workflow.reliability.continue_on_error_abuse

import rego.v1

# Detects steps that set continue-on-error: true, which silently swallows
# failures and may allow broken workflows to appear green.

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	step["continue-on-error"] == true

	# The default argument is evaluated eagerly, so a bare `step.uses` there
	# makes the whole rule undefined for run-only steps without a `uses` key.
	step_name := object.get(step, "name", object.get(step, "uses", "unnamed step"))
	violation := {
		"rule": "continue_on_error_abuse",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"step": object.get(step, "uses", null),
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' uses continue-on-error: true. Failures will be silently ignored, masking real problems.", [step_name, job_name]),
		"context": "continue-on-error: true",
	}
}
