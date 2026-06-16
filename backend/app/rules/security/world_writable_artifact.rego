package greensecops.security.world_writable_artifact

import rego.v1

violations contains violation if {
	some job_name, job in input.jobs
	some step in job.steps
	uses := step.uses
	startswith(uses, "actions/upload-artifact")
	with_block := step["with"]
	not _has_retention(with_block)
	violation := {
		"rule": "world_writable_artifact",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' uploads artifacts without explicit retention-days. Artifacts are world-readable by default; set retention-days to limit exposure window.", [job_name]),
		"context": sprintf("%v", [uses]),
	}
}

_has_retention(with_block) if {
	with_block["retention-days"]
}
