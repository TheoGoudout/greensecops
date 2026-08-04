# METADATA
# title: Concurrency group without cancel-in-progress
# description: A concurrency group is declared but cancel-in-progress is not enabled, so a superseded run is queued behind the current one rather than stopped. The queued run then executes against a commit nobody is waiting on any more, and on a branch that is pushed to several times in a row the queue grows faster than it drains. The group already establishes that only the newest run matters; this is the setting that acts on it.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       concurrency:
#         group: ci-${{ github.ref }}
#     good: |
#       concurrency:
#         group: ci-${{ github.ref }}
#         cancel-in-progress: true
#     fix: |
#       Set cancel-in-progress: true. Leave it off only where a run must not be interrupted part-way — a deployment or a release — in which case the group is doing serialisation rather than deduplication, and that is a deliberate different thing.
package greensecops.ci_workflow.energy.concurrency_without_cancel

import rego.v1

# A bare string is the shorthand for a group with no other settings, so it
# cannot have cancel-in-progress either.
_declares_group(concurrency) if is_string(concurrency)

_declares_group(concurrency) if {
	is_object(concurrency)
	concurrency.group
}

_cancels(concurrency) if {
	is_object(concurrency)
	concurrency["cancel-in-progress"] == true
}

# The value is often an expression rather than a literal, which is still a
# deliberate decision the rule should not second-guess.
_cancels(concurrency) if {
	is_object(concurrency)
	value := concurrency["cancel-in-progress"]
	is_string(value)
	trim_space(value) != ""
}

violations contains violation if {
	concurrency := input.concurrency
	_declares_group(concurrency)
	not _cancels(concurrency)

	violation := {
		"rule": "concurrency_without_cancel",
		"severity": "low",
		"category": "energy",
		"message": "A concurrency group is declared but superseded runs are queued rather than cancelled, so they still execute against a commit nobody is waiting on. Set cancel-in-progress: true.",
		"context": "concurrency",
		"discriminator": "workflow",
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	concurrency := job.concurrency
	_declares_group(concurrency)
	not _cancels(concurrency)

	violation := {
		"rule": "concurrency_without_cancel",
		"severity": "low",
		"category": "energy",
		"job": job_name,
		"message": sprintf("Job '%v' declares a concurrency group but queues superseded runs rather than cancelling them. Set cancel-in-progress: true.", [job_name]),
		"context": "concurrency",
		"discriminator": job_name,
	}
}
