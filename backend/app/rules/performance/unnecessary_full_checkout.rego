package greensecops.performance.unnecessary_full_checkout

import rego.v1

_uses_git_history(steps) if {
    some step in steps
    run := step.run
    some cmd in ["git log", "git describe", "git tag", "git blame", "git shortlog", "CHANGELOG", "gitversion", "semantic-release", "standard-version"]
    contains(run, cmd)
}

violations contains violation if {
    some job_name, job in input.jobs
    some step in job.steps
    uses := step.uses
    startswith(uses, "actions/checkout")
    step["with"]["fetch-depth"] == 0
    not _uses_git_history(job.steps)
    violation := {
        "rule": "unnecessary_full_checkout",
        "severity": "low",
        "category": "performance",
        "job": job_name,
        "message": sprintf("Job '%v' uses fetch-depth: 0 but no git history commands found. Remove fetch-depth: 0 to speed up checkout.", [job_name]),
        "context": "fetch-depth: 0",
    }
}
