package greensecops.maintainability.workflow_too_complex

import rego.v1

# Detects workflows where the total number of steps across all jobs exceeds 20,
# which is a signal that the workflow should be split or refactored.

_total_steps := sum([count(job.steps) | some _, job in input.jobs])

violations contains violation if {
    total := _total_steps
    total > 20
    violation := {
        "rule": "workflow_too_complex",
        "severity": "info",
        "category": "maintainability",
        "job": null,
        "message": sprintf("Workflow has %v total steps across all jobs (threshold: 20). Consider splitting into smaller, focused workflows.", [total]),
        "context": null,
    }
}
