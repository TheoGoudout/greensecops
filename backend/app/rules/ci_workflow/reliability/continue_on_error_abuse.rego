# METADATA
# title: "continue-on-error masking failures"
# description: "A step sets continue-on-error: true without anything downstream reading its outcome, so a failure is discarded rather than handled. The legitimate uses all leave a trace — a later step branching on steps.<id>.outcome, a job-level if:, or an upload that is genuinely optional — and those are not reported. What is left is a step whose failure nobody will ever notice."
# custom:
#   severity: medium
#   severity_weight: 1.2
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         ci:
#           runs-on: ubuntu-latest
#           steps:
#             - name: Run tests
#               run: npm test
#               continue-on-error: true
#     good: |
#       jobs:
#         ci:
#           runs-on: ubuntu-latest
#           steps:
#             - name: Run tests
#               id: tests
#               run: npm test
#               continue-on-error: true
#             - name: Report
#               if: steps.tests.outcome == 'failure'
#               run: ./report-failure.sh
#     fix: |
#       Either remove continue-on-error and let the failure fail the job, or give the step an id and act on steps.<id>.outcome afterwards. A swallowed failure that nothing reads is a green run hiding a broken build.
package greensecops.ci_workflow.reliability.continue_on_error_abuse

import rego.v1

# Uploads and reports that are genuinely best-effort: the run's purpose does not
# depend on them, and failing the build because a coverage service was briefly
# down helps nobody.
_optional_action_patterns := [
	"codecov/codecov-action",
	"coverallsapp/github-action",
	"smokeshow",
	"actions/upload-artifact",
	"github/codeql-action/upload-sarif",
]

_is_optional_upload(step) if {
	some pattern in _optional_action_patterns
	contains(step.uses, pattern)
}

# The outcome is read somewhere, so the failure is handled rather than
# discarded. This is the whole legitimate pattern, and the previous version had
# no way to see it — its own `fix:` text told authors to "add a comment
# explaining why", which the rule could not read.
_outcome_is_consumed(job, step) if {
	step_id := step.id
	is_string(step_id)
	pattern := sprintf(`steps\.%v\.(outcome|conclusion)`, [regex.replace(step_id, `[.*+?^${}()|\[\]\\]`, `\\$0`)])
	regex.match(pattern, json.marshal(job))
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	step["continue-on-error"] == true

	not _is_optional_upload(step)
	not _outcome_is_consumed(job, step)

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
		"message": sprintf("Step '%v' in job '%v' sets continue-on-error: true and nothing reads its outcome, so a failure is discarded silently. Give the step an id and branch on steps.<id>.outcome, or let it fail.", [step_name, job_name]),
		"context": "continue-on-error: true",
	}
}
