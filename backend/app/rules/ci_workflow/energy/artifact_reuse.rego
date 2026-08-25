# METADATA
# title: Uploaded artifact that nothing in the workflow downloads
# description: "A job uploads an artifact and no job in the workflow downloads it. Uploading costs the compression, the transfer and the storage on every run, so an artifact nobody reads is paid for repeatedly and read never. Diagnostics are excluded — a coverage file, a log bundle or a test report is uploaded to be read by a person, not by a later job — and so is any artifact a `workflow_run` or `download-artifact` step in the same file consumes."
# custom:
#   severity: low
#   severity_weight: 0.8
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: make dist
#             - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
#               with: {name: dist, path: dist/}
#         deploy:
#           needs: build
#           runs-on: ubuntu-latest
#           steps:
#             - run: make dist && ./deploy.sh
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: make dist
#             - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
#               with: {name: dist, path: dist/}
#         deploy:
#           needs: build
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
#               with: {name: dist, path: dist/}
#             - run: ./deploy.sh
#     fix: |
#       Download the artifact in the job that needs it instead of rebuilding, or drop the upload if nothing consumes it. Where the artifact is genuinely for a human — a report, a log, a coverage file — name it so, and this rule leaves it alone.
package greensecops.ci_workflow.energy.artifact_reuse

import data.greensecops.lib.workflow as wf
import rego.v1

# This used to report the *downstream* job: "you depend on a job that uploads
# and you don't download". That is not a defect — the consumer may be a
# `workflow_run` in another file, a third-party downloader, or a person opening
# the run page — and it blamed a job that had done nothing wrong. What is
# actually reportable is an upload that no job in this workflow reads, and it
# belongs to the job doing the uploading.

_uploads(step) if contains(object.get(step, "uses", ""), "actions/upload-artifact")

# Any downloader, not only the first-party one: `dawidd6/action-download-artifact`
# and friends read the same store.
_downloads(step) if contains(lower(object.get(step, "uses", "")), "download-artifact")

_any_job_downloads if {
	some _, job in input.jobs
	some step in job.steps
	_downloads(step)
}

# Uploaded to be looked at rather than consumed. Same vocabulary as
# `artifact_upload_without_always`, which decides the same question in the
# other direction.
_diagnostic_pattern := `(?i)(log|report|result|coverage|screenshot|trace|dump|junit|diagnos|sarif|profile)`

_is_diagnostic(step) if regex.match(_diagnostic_pattern, object.get(object.get(step, "with", {}), "name", ""))

_is_diagnostic(step) if regex.match(_diagnostic_pattern, object.get(object.get(step, "with", {}), "path", ""))

# A workflow whose whole purpose is to hand something to another workflow run
# cannot be judged from this file alone.
_consumed_elsewhere if wf.has_trigger("workflow_call")

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_uploads(step)
	not _is_diagnostic(step)
	not _any_job_downloads
	not _consumed_elsewhere

	name := object.get(object.get(step, "with", {}), "name", "the artifact")
	violation := {
		"rule": "artifact_reuse",
		"severity": "low",
		"category": "energy",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"line_start": object.get(step, "__start_line__", null),
		"line_end": object.get(step, "__end_line__", null),
		"message": sprintf("Job '%v' uploads '%v' and no job in this workflow downloads it. Where a later job rebuilds what this produced, download it instead; where the artifact is the workflow's deliverable rather than an intermediate, this is working as intended.", [job_name, name]),
		"context": sprintf("%v", [name]),
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
