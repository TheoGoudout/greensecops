# METADATA
# title: Diagnostic artifact is only uploaded when the job succeeds
# description: A step uploads an artifact whose name suggests it exists for diagnosis — logs, a test report, a coverage file, a screenshot — with no `if` condition, so it is skipped whenever an earlier step fails. That is precisely backwards. A step's default condition is success, so the artifact is uploaded on the runs where nobody needs it and skipped on the runs where somebody is trying to work out what went wrong. The result is a failed job whose evidence was discarded with the runner, and a re-run to collect what the first run already had.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         test:
#           steps:
#             - run: pytest --junitxml=report.xml
#             - uses: actions/upload-artifact@v4
#               with:
#                 name: test-report
#                 path: report.xml
#     good: |
#       jobs:
#         test:
#           steps:
#             - run: pytest --junitxml=report.xml
#             - uses: actions/upload-artifact@v4
#               if: always()
#               with:
#                 name: test-report
#                 path: report.xml
#     fix: |
#       Add `if: always()` to the upload step, or `if: failure()` where the artifact is only ever of interest on a failure. Both override the implicit success condition; always() is the safer default because it keeps the artifact for a flaky run that passed on a retry.
package greensecops.ci_workflow.reliability.artifact_upload_without_always

import rego.v1

_diagnostic_pattern := `(?i)(log|report|result|coverage|screenshot|trace|dump|junit|diagnos)`

_runs_on_failure(step) if {
	condition := lower(sprintf("%v", [object.get(step, "if", "")]))
	some marker in ["always()", "failure()", "cancelled()", "!cancelled()"]
	contains(condition, marker)
}

_is_diagnostic(step) if regex.match(_diagnostic_pattern, object.get(object.get(step, "with", {}), "name", ""))

_is_diagnostic(step) if regex.match(_diagnostic_pattern, object.get(object.get(step, "with", {}), "path", ""))

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps

	contains(object.get(step, "uses", ""), "actions/upload-artifact")
	_is_diagnostic(step)
	not _runs_on_failure(step)

	violation := {
		"rule": "artifact_upload_without_always",
		"severity": "low",
		"category": "reliability",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"line_start": object.get(step, "__start_line__", null),
		"line_end": object.get(step, "__end_line__", null),
		"message": sprintf("Job '%v' uploads a diagnostic artifact with no 'if' condition, so it is skipped on exactly the runs that fail. Add 'if: always()'.", [job_name]),
		"context": step.uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
