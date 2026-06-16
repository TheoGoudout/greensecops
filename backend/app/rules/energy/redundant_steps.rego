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
	some step in job.steps
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
		"message": sprintf("Action '%v' is used in %v jobs. Consider consolidating or sharing results to avoid redundant work.", [base, count(jobs_using)]),
		"context": uses,
	}
}
