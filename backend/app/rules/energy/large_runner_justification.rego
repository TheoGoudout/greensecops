package greensecops.energy.large_runner_justification

import rego.v1

# Detects jobs that use GPU or large runners without any step that justifies
# the heavy resource (train, compile, build, cmake, cargo build).

_is_large_runner(runner) if {
	contains(runner, "gpu")
}

_is_large_runner(runner) if {
	contains(runner, "large")
}

_has_heavy_workload(steps) if {
	some step in steps
	run := step.run
	some keyword in ["train", "compile", "build", "cmake", "cargo build"]
	contains(run, keyword)
}

violations contains violation if {
	some job_name, job in input.jobs
	runner := job["runs-on"]
	is_string(runner)
	_is_large_runner(runner)
	not _has_heavy_workload(job.steps)
	violation := {
		"rule": "large_runner_justification",
		"severity": "high",
		"category": "energy",
		"job": job_name,
		"message": sprintf("Job '%v' uses a GPU/large runner ('%v') but no compute-intensive steps (train, compile, build, cmake, cargo build) were found.", [job_name, runner]),
		"context": runner,
	}
}
