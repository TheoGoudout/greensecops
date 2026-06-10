package greensecops.maintainability.no_reusable_workflow_test

import rego.v1
import data.greensecops.maintainability.no_reusable_workflow

test_violation_identical_step_actions_in_two_jobs if {
    violations := no_reusable_workflow.violations with input as {
        "jobs": {
            "job1": {
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {"uses": "actions/setup-node@v4"}
                ]
            },
            "job2": {
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {"uses": "actions/setup-node@v4"}
                ]
            }
        }
    }
    count(violations) > 0
    some v in violations
    v.rule == "no_reusable_workflow"
}

test_no_violation_different_step_actions if {
    violations := no_reusable_workflow.violations with input as {
        "jobs": {
            "job1": {
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {"uses": "actions/setup-node@v4"}
                ]
            },
            "job2": {
                "steps": [
                    {"uses": "actions/checkout@v4"},
                    {"uses": "actions/setup-python@v5"}
                ]
            }
        }
    }
    count(violations) == 0
}

test_no_violation_steps_with_no_uses if {
    violations := no_reusable_workflow.violations with input as {
        "jobs": {
            "job1": {"steps": [{"run": "echo hello"}]},
            "job2": {"steps": [{"run": "echo hello"}]}
        }
    }
    count(violations) == 0
}
