package greensecops.security.pr_target_injection

import rego.v1

# Detects the dangerous pattern of triggering on pull_request_target AND
# checking out the PR head ref, which can execute untrusted code with
# write permissions in the base repository context.

_triggers_on_pr_target if {
	input.on.pull_request_target
}

_triggers_on_pr_target if {
	some trigger in input.on
	trigger == "pull_request_target"
}

_has_head_checkout(step) if {
	contains(step.uses, "actions/checkout")
	ref := step["with"].ref
	contains(ref, "github.event.pull_request.head")
}

violations contains violation if {
	_triggers_on_pr_target
	some job_name, job in input.jobs
	some step in job.steps
	_has_head_checkout(step)
	violation := {
		"rule": "pr_target_injection",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' triggers on pull_request_target and checks out the PR head ref. This allows untrusted code to run with write access. See GitHub Security Lab advisory.", [job_name]),
		"context": "pull_request_target + checkout head ref",
	}
}
