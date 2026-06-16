package greensecops.maintainability.hardcoded_env_values_test

import data.greensecops.maintainability.hardcoded_env_values
import rego.v1

test_violation_hardcoded_url if {
	violations := hardcoded_env_values.violations with input as {
		"env": {"API_BASE_URL": "https://api.example.com"},
		"jobs": {},
	}
	count(violations) == 1
	some v in violations
	v.rule == "hardcoded_env_values"
}

test_violation_hardcoded_bucket_name if {
	violations := hardcoded_env_values.violations with input as {
		"env": {"STORAGE": "my-app-artifacts"},
		"jobs": {},
	}
	count(violations) == 1
	some v in violations
	v.rule == "hardcoded_env_values"
}

test_no_violation_secret_ref_url if {
	violations := hardcoded_env_values.violations with input as {
		"env": {"API_BASE_URL": "${{ vars.API_BASE_URL }}"},
		"jobs": {},
	}
	count(violations) == 0
}

test_no_violation_plain_string_not_url_or_bucket if {
	violations := hardcoded_env_values.violations with input as {
		"env": {"NODE_ENV": "production", "LOG_LEVEL": "info"},
		"jobs": {},
	}
	count(violations) == 0
}
