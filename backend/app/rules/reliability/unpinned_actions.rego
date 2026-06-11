package greensecops.reliability.unpinned_actions

import rego.v1

# Detects steps that reference a mutable git ref (@main, @master, @latest,
# or a bare semver tag like @v3) instead of a full SHA, making the workflow
# vulnerable to supply-chain attacks and non-deterministic behaviour.

_is_mutable_ref(uses) if {
    some mutable in ["@main", "@master", "@latest"]
    endswith(uses, mutable)
}

_is_mutable_ref(uses) if {
    # Matches @v followed by digits only (e.g. @v3, @v12) — not a SHA
    ref := split(uses, "@")[1]
    startswith(ref, "v")
    regex.match(`^v[0-9]+$`, ref)
}

violations contains violation if {
    some job_name, job in input.jobs
    some step in job.steps
    uses := step.uses
    uses != null
    _is_mutable_ref(uses)
    violation := {
        "rule": "unpinned_actions",
        "severity": "high",
        "category": "reliability",
        "job": job_name,
        "message": sprintf("Step in job '%v' uses a mutable ref '%v'. Pin to a full commit SHA for reproducibility and supply-chain safety.", [job_name, uses]),
        "context": uses,
    }
}
