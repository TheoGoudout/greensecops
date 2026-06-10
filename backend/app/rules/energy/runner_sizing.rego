package greensecops.energy.runner_sizing

import rego.v1

# Detects jobs that request large/expensive runners but have 3 or fewer steps,
# suggesting the heavy runner is not justified by the workload.

_large_runner(runner) if {
    some label in ["large", "xlarge", "2xlarge", "8-core", "16-core", "ubuntu-latest-8"]
    contains(runner, label)
}

violations contains violation if {
    some job_name, job in input.jobs
    runner := job["runs-on"]
    is_string(runner)
    _large_runner(runner)
    count(job.steps) <= 3
    violation := {
        "rule": "runner_sizing",
        "severity": "medium",
        "category": "energy",
        "job": job_name,
        "message": sprintf("Job '%v' uses a large runner ('%v') but has only %v step(s). Downsize the runner to reduce energy consumption.", [job_name, runner, count(job.steps)]),
        "context": runner,
    }
}
