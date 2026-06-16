package greensecops.maintainability.no_reusable_workflow

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
