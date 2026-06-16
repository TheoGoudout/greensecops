package greensecops.reliability.missing_timeout

import rego.v1

violations contains violation if {
	some job_name, job in input.jobs
	not job["timeout-minutes"]
	violation := {
		"rule": "missing_timeout",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Job '%v' has no timeout-minutes configured. Without a timeout a hung job runs for up to 6 hours.", [job_name]),
		"context": null,
	}
}
