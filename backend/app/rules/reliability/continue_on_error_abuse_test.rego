package greensecops.reliability.continue_on_error_abuse_test

import rego.v1
import data.greensecops.reliability.continue_on_error_abuse

test_violation_step_with_continue_on_error if {
    violations := continue_on_error_abuse.violations with input as {
        "jobs": {
            "build": {
                "steps": [{
                    "name": "Flaky step",
                    "run": "some-flaky-command",
                    "continue-on-error": true
                }]
            }
        }
    }
    count(violations) == 1
    some v in violations
    v.rule == "continue_on_error_abuse"
    v.job == "build"
}

test_no_violation_no_continue_on_error if {
    violations := continue_on_error_abuse.violations with input as {
        "jobs": {
            "build": {
                "steps": [{"name": "Build", "run": "make build"}]
            }
        }
    }
    count(violations) == 0
}

test_no_violation_continue_on_error_false if {
    violations := continue_on_error_abuse.violations with input as {
        "jobs": {
            "build": {
                "steps": [{
                    "name": "Safe step",
                    "run": "echo hi",
                    "continue-on-error": false
                }]
            }
        }
    }
    count(violations) == 0
}
