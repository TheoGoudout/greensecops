package greensecops.security.untrusted_actions_test

import rego.v1
import data.greensecops.security.untrusted_actions

test_violation_third_party_mutable_tag if {
    violations := untrusted_actions.violations with input as {
        "jobs": {
            "build": {
                "steps": [{"uses": "some-org/some-action@v2"}]
            }
        }
    }
    count(violations) == 1
    some v in violations
    v.rule == "untrusted_actions"
}

test_no_violation_third_party_sha_pinned if {
    violations := untrusted_actions.violations with input as {
        "jobs": {
            "build": {
                "steps": [{"uses": "some-org/some-action@a81bbbf8298c0fa03ea29cdc473d45769f953675"}]
            }
        }
    }
    count(violations) == 0
}

test_no_violation_first_party_actions if {
    violations := untrusted_actions.violations with input as {
        "jobs": {
            "build": {
                "steps": [{"uses": "actions/checkout@v4"}]
            }
        }
    }
    count(violations) == 0
}

test_no_violation_github_org_action if {
    violations := untrusted_actions.violations with input as {
        "jobs": {
            "build": {
                "steps": [{"uses": "github/codeql-action@v3"}]
            }
        }
    }
    count(violations) == 0
}
