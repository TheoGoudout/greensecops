package greensecops.reliability.continue_on_error_abuse

import rego.v1

# Detects steps that set continue-on-error: true, which silently swallows
# failures and may allow broken workflows to appear green.

violations contains violation if {
	some job_name, job in input.jobs
	some step in job.steps
	step["continue-on-error"] == true
	step_name := object.get(step, "name", step.uses)
	violation := {
		"rule": "continue_on_error_abuse",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Step '%v' in job '%v' uses continue-on-error: true. Failures will be silently ignored, masking real problems.", [step_name, job_name]),
		"context": "continue-on-error: true",
	}
}
