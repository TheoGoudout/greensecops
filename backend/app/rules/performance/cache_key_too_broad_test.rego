package greensecops.performance.cache_key_too_broad_test

import rego.v1
import data.greensecops.performance.cache_key_too_broad

test_violation_cache_key_without_hashfiles if {
    violations := cache_key_too_broad.violations with input as {
        "jobs": {
            "build": {
                "steps": [{
                    "uses": "actions/cache@v4",
                    "with": {
                        "path": "~/.npm",
                        "key": "node-modules-${{ runner.os }}"
                    }
                }]
            }
        }
    }
    count(violations) == 1
    some v in violations
    v.rule == "cache_key_too_broad"
}

test_no_violation_cache_key_with_hashfiles if {
    violations := cache_key_too_broad.violations with input as {
        "jobs": {
            "build": {
                "steps": [{
                    "uses": "actions/cache@v4",
                    "with": {
                        "path": "~/.npm",
                        "key": "node-${{ runner.os }}-${{ hashFiles('**/package-lock.json') }}"
                    }
                }]
            }
        }
    }
    count(violations) == 0
}

test_no_violation_no_cache_step if {
    violations := cache_key_too_broad.violations with input as {
        "jobs": {
            "build": {
                "steps": [{"uses": "actions/checkout@v4"}]
            }
        }
    }
    count(violations) == 0
}
