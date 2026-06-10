package greensecops.reliability.missing_concurrency

import rego.v1

# Detects workflows triggered by pull_request or pull_request_target that do
# not define a top-level concurrency group, which can lead to redundant
# concurrent runs for the same PR.

_has_pr_trigger if {
    input.on["pull_request"]
}

_has_pr_trigger if {
    input.on["pull_request_target"]
}

_has_pr_trigger if {
    some trigger in input.on
    trigger == "pull_request"
}

_has_pr_trigger if {
    some trigger in input.on
    trigger == "pull_request_target"
}

violations contains violation if {
    _has_pr_trigger
    not input.concurrency
    violation := {
        "rule": "missing_concurrency",
        "severity": "medium",
        "category": "reliability",
        "job": null,
        "message": "Workflow triggers on pull_request/pull_request_target but has no top-level 'concurrency:' group. Add concurrency to cancel redundant runs on new pushes.",
        "context": null,
    }
}
