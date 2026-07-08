# METADATA
# title: No explicit artifact retention
# description: Uploaded artifacts use the default 90-day retention. Set retention-days explicitly to control storage costs and data lifecycle.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/upload-artifact@v4
#               with:
#                 name: dist
#                 path: dist/
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/upload-artifact@v4
#               with:
#                 name: dist
#                 path: dist/
#                 retention-days: 7
#     fix: |
#       Add retention-days to every actions/upload-artifact step. Choose a value appropriate for the artifact's purpose (e.g. 1 day for PR previews, 30 days for release assets).
package greensecops.reliability.artifact_retention

import rego.v1

# Detects artifact upload steps that do not specify retention-days, which
# causes GitHub to apply the account default (often 90 days), accumulating
# storage costs and cluttering the artifact list.

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	contains(step.uses, "actions/upload-artifact")
	not step["with"]["retention-days"]
	violation := {
		"rule": "artifact_retention",
		"severity": "low",
		"category": "reliability",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' uploads an artifact without setting 'retention-days'. Set an explicit retention period to control storage costs.", [job_name]),
		"context": step.uses,
	}
}
