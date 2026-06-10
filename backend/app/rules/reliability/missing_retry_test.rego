package greensecops.reliability.missing_retry_test

import rego.v1
import data.greensecops.reliability.missing_retry

test_violation_curl_without_retry if {
    violations := missing_retry.violations with input as {
        "jobs": {
            "fetch": {
                "steps": [{"run": "curl https://example.com/data.json -o data.json"}]
            }
        }
    }
    count(violations) == 1
    some v in violations
    v.rule == "missing_retry"
}

test_no_violation_network_step_with_retry_action if {
    violations := missing_retry.violations with input as {
        "jobs": {
            "fetch": {
                "steps": [
                    {"run": "npm install"},
                    {"uses": "nick-fields/retry@v2", "with": {"command": "npm install"}}
                ]
            }
        }
    }
    count(violations) == 0
}

test_no_violation_no_network_commands if {
    violations := missing_retry.violations with input as {
        "jobs": {
            "lint": {
                "steps": [{"run": "eslint ."}]
            }
        }
    }
    count(violations) == 0
}

test_violation_pip_install_without_retry if {
    violations := missing_retry.violations with input as {
        "jobs": {
            "setup": {
                "steps": [{"run": "pip install -r requirements.txt"}]
            }
        }
    }
    count(violations) == 1
}
