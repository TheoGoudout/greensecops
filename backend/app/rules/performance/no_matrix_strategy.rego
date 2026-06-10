package greensecops.performance.no_matrix_strategy

import rego.v1

# Detects when 3 or more jobs share the same runner and identical first-step
# action but none defines a strategy.matrix, suggesting they could be collapsed
# into a single parameterised matrix job.

_first_step_action(job) := action if {
    count(job.steps) > 0
    step := job.steps[0]
    action := split(step.uses, "@")[0]
}

_job_signature(job) := sig if {
    runner := job["runs-on"]
    action := _first_step_action(job)
    sig := {"runner": runner, "action": action}
}

_jobs_with_signature(sig) := {job_name |
    some job_name, job in input.jobs
    _job_signature(job) == sig
    not job.strategy
}

violations contains violation if {
    some job_name, job in input.jobs
    not job.strategy
    sig := _job_signature(job)
    matching := _jobs_with_signature(sig)
    count(matching) >= 3
    violation := {
        "rule": "no_matrix_strategy",
        "severity": "medium",
        "category": "performance",
        "job": job_name,
        "message": sprintf("Job '%v' is one of %v jobs with identical runner and first step. Consider using a strategy.matrix to eliminate duplication.", [job_name, count(matching)]),
        "context": null,
    }
}
