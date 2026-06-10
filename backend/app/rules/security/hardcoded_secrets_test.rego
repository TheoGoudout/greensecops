package greensecops.security.hardcoded_secrets_test

import rego.v1
import data.greensecops.security.hardcoded_secrets

test_violation_plaintext_api_key if {
    violations := hardcoded_secrets.violations with input as {
        "env": {"API_KEY": "abc123supersecret"},
        "jobs": {}
    }
    count(violations) == 1
    some v in violations
    v.rule == "hardcoded_secrets"
    v.job == null
}

test_no_violation_secret_ref if {
    violations := hardcoded_secrets.violations with input as {
        "env": {"API_KEY": "${{ secrets.MY_API_KEY }}"},
        "jobs": {}
    }
    count(violations) == 0
}

test_violation_token_in_job_env if {
    violations := hardcoded_secrets.violations with input as {
        "jobs": {
            "deploy": {
                "env": {"TOKEN": "hardcoded-token-value"},
                "steps": []
            }
        }
    }
    count(violations) == 1
    some v in violations
    v.job == "deploy"
}

test_no_violation_vars_ref if {
    violations := hardcoded_secrets.violations with input as {
        "env": {"PASSWORD": "${{ vars.DB_PASSWORD }}"},
        "jobs": {}
    }
    count(violations) == 0
}

test_no_violation_unrelated_env_var if {
    violations := hardcoded_secrets.violations with input as {
        "env": {"NODE_ENV": "production"},
        "jobs": {}
    }
    count(violations) == 0
}
