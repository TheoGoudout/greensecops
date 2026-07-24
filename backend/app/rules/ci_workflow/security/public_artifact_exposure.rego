# METADATA
# title: Artifact uploaded without retention limit
# description: Job uploads artifacts without an explicit retention-days setting. GitHub Actions artifacts are publicly readable for 90 days by default; limiting the retention window reduces the exposure of potentially sensitive build outputs.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/upload-artifact@v4
#               with:
#                 name: release-binary
#                 path: dist/app
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/upload-artifact@v4
#               with:
#                 name: release-binary
#                 path: dist/app
#                 retention-days: 3
#     fix: |
#       Set retention-days on every actions/upload-artifact step to limit the window during which build outputs are publicly accessible. Use the shortest duration sufficient for downstream consumption.
package greensecops.ci_workflow.security.public_artifact_exposure

import rego.v1

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	startswith(uses, "actions/upload-artifact")
	with_block := step["with"]
	not _has_retention(with_block)
	violation := {
		"rule": "public_artifact_exposure",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Job '%v' uploads artifacts without explicit retention-days. Artifacts are world-readable by default; set retention-days to limit exposure window.", [job_name]),
		"context": sprintf("%v", [uses]),
	}
}

_has_retention(with_block) if {
	with_block["retention-days"]
}
