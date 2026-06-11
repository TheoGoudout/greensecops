package greensecops.performance.no_matrix_strategy_test

import rego.v1
import data.greensecops.performance.no_matrix_strategy

test_violation_three_identical_jobs_no_matrix if {
    violations := no_matrix_strategy.violations with input as {
        "jobs": {
            "test-node16": {
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/setup-node@v4"}, {"run": "npm test"}]
            },
            "test-node18": {
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/setup-node@v4"}, {"run": "npm test"}]
            },
            "test-node20": {
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/setup-node@v4"}, {"run": "npm test"}]
            }
        }
    }
    count(violations) > 0
    some v in violations
    v.rule == "no_matrix_strategy"
}

test_no_violation_matrix_strategy_defined if {
    violations := no_matrix_strategy.violations with input as {
        "jobs": {
            "test": {
                "runs-on": "ubuntu-latest",
                "strategy": {"matrix": {"node": [16, 18, 20]}},
                "steps": [{"uses": "actions/setup-node@v4"}, {"run": "npm test"}]
            }
        }
    }
    count(violations) == 0
}

test_no_violation_different_runners if {
    violations := no_matrix_strategy.violations with input as {
        "jobs": {
            "test-linux": {
                "runs-on": "ubuntu-latest",
                "steps": [{"uses": "actions/setup-node@v4"}]
            },
            "test-mac": {
                "runs-on": "macos-latest",
                "steps": [{"uses": "actions/setup-node@v4"}]
            },
            "test-win": {
                "runs-on": "windows-latest",
                "steps": [{"uses": "actions/setup-node@v4"}]
            }
        }
    }
    count(violations) == 0
}
