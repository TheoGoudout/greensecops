package greensecops.maintainability.missing_workflow_description

import rego.v1

violations contains violation if {
	not input.name
	violation := {
		"rule": "missing_workflow_description",
		"severity": "info",
		"category": "maintainability",
		"job": null,
		"message": "Workflow has no top-level 'name' field. Add a descriptive name to improve CI log readability.",
		"context": null,
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	not job.name
	violation := {
		"rule": "missing_workflow_description",
		"severity": "info",
		"category": "maintainability",
		"job": job_name,
		"message": sprintf("Job '%v' has no 'name' field. Add a human-readable name to improve CI readability.", [job_name]),
		"context": null,
	}
}
