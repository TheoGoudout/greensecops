package greensecops.reliability.artifact_retention

import rego.v1

# Detects artifact upload steps that do not specify retention-days, which
# causes GitHub to apply the account default (often 90 days), accumulating
# storage costs and cluttering the artifact list.

violations contains violation if {
    some job_name, job in input.jobs
    some step in job.steps
    contains(step.uses, "actions/upload-artifact")
    not step["with"]["retention-days"]
    violation := {
        "rule": "artifact_retention",
        "severity": "low",
        "category": "reliability",
        "job": job_name,
        "message": sprintf("Step in job '%v' uploads an artifact without setting 'retention-days'. Set an explicit retention period to control storage costs.", [job_name]),
        "context": step.uses,
    }
}
