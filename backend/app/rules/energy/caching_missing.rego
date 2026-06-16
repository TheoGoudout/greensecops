package greensecops.energy.caching_missing

import rego.v1

_has_cache_action(steps) if {
	some step in steps
	uses := step.uses
	contains(uses, "actions/cache")
}

_has_cache_action(steps) if {
	some step in steps
	uses := step.uses
	startswith(uses, "actions/setup-")
	step["with"].cache
}

_uses_package_manager(steps) if {
	some step in steps
	run := step.run
	some pm in ["npm ", "yarn ", "pip ", "pip3 ", "poetry ", "gradle ", "cargo ", "mvn ", "pnpm ", "bun "]
	contains(run, pm)
}

violations contains violation if {
	some job_name, job in input.jobs
	steps := job.steps
	_uses_package_manager(steps)
	not _has_cache_action(steps)
	violation := {
		"rule": "caching_missing",
		"severity": "high",
		"category": "energy",
		"job": job_name,
		"message": sprintf("Job '%v' installs dependencies without caching. Add actions/cache or use setup-* with cache: true.", [job_name]),
		"context": null,
	}
}
