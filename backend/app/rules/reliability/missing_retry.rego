package greensecops.reliability.missing_retry

import rego.v1

# Detects jobs that run network-dependent commands (curl, wget, pip install,
# npm install, apt-get) without any retry action, making them fragile against
# transient network failures.

_network_commands := ["curl", "wget", "pip install", "npm install", "apt-get"]

_has_network_step(steps) if {
    some step in steps
    run := step.run
    some cmd in _network_commands
    contains(run, cmd)
}

_has_retry_action(steps) if {
    some step in steps
    uses := step.uses
    contains(uses, "retry")
}

violations contains violation if {
    some job_name, job in input.jobs
    _has_network_step(job.steps)
    not _has_retry_action(job.steps)
    violation := {
        "rule": "missing_retry",
        "severity": "medium",
        "category": "reliability",
        "job": job_name,
        "message": sprintf("Job '%v' runs network-dependent commands (curl/wget/pip/npm/apt-get) without a retry action. Consider adding a retry mechanism for transient failures.", [job_name]),
        "context": null,
    }
}
