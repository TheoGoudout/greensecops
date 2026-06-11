package greensecops.maintainability.workflow_too_complex_test

import rego.v1
import data.greensecops.maintainability.workflow_too_complex

test_violation_total_steps_exceeds_20 if {
    violations := workflow_too_complex.violations with input as {
        "jobs": {
            "job1": {"steps": [
                {"run": "s1"}, {"run": "s2"}, {"run": "s3"}, {"run": "s4"}, {"run": "s5"},
                {"run": "s6"}, {"run": "s7"}, {"run": "s8"}, {"run": "s9"}, {"run": "s10"},
                {"run": "s11"}
            ]},
            "job2": {"steps": [
                {"run": "s1"}, {"run": "s2"}, {"run": "s3"}, {"run": "s4"}, {"run": "s5"},
                {"run": "s6"}, {"run": "s7"}, {"run": "s8"}, {"run": "s9"}, {"run": "s10"},
                {"run": "s11"}
            ]}
        }
    }
    count(violations) == 1
    some v in violations
    v.rule == "workflow_too_complex"
}

test_no_violation_steps_at_threshold if {
    violations := workflow_too_complex.violations with input as {
        "jobs": {
            "job1": {"steps": [
                {"run": "s1"}, {"run": "s2"}, {"run": "s3"}, {"run": "s4"}, {"run": "s5"},
                {"run": "s6"}, {"run": "s7"}, {"run": "s8"}, {"run": "s9"}, {"run": "s10"}
            ]},
            "job2": {"steps": [
                {"run": "s1"}, {"run": "s2"}, {"run": "s3"}, {"run": "s4"}, {"run": "s5"},
                {"run": "s6"}, {"run": "s7"}, {"run": "s8"}, {"run": "s9"}, {"run": "s10"}
            ]}
        }
    }
    count(violations) == 0
}

test_no_violation_small_workflow if {
    violations := workflow_too_complex.violations with input as {
        "jobs": {
            "build": {"steps": [{"run": "make build"}]},
            "test": {"steps": [{"run": "make test"}]}
        }
    }
    count(violations) == 0
}
