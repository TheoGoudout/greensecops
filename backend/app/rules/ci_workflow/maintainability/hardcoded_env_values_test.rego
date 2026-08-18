package greensecops.ci_workflow.maintainability.hardcoded_env_values_test

import data.greensecops.ci_workflow.maintainability.hardcoded_env_values
import rego.v1

test_violation_hardcoded_url if {
	violations := hardcoded_env_values.violations with input as {
		"env": {"API_BASE_URL": "https://api.production.example.com"},
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
}

test_violation_in_job_and_step_env if {
	violations := hardcoded_env_values.violations with input as {"jobs": {"deploy": {
		"env": {"JOB_URL": "https://job.example.com"},
		"steps": [{"env": {"STEP_URL": "https://step.example.com"}}],
	}}}
	count(violations) == 2
}

test_no_violation_secret_ref_url if {
	violations := hardcoded_env_values.violations with input as {
		"env": {"API_BASE_URL": "${{ vars.API_BASE_URL }}"},
		"jobs": {},
	}
	count(violations) == 0
}

# ─── The false positives this rework exists to remove ─────────────────────────

# A loopback address is not "the production URL", it is "this runner". These are
# the exact values in this repository's test-backend, test-docker-compose and
# playwright workflows, pointing at containers the job starts itself.
test_no_violation_loopback_addresses if {
	violations := hardcoded_env_values.violations with input as {
		"env": {
			"SERVICE_URL_BACKEND": "http://localhost:8000",
			"SERVICE_URL_FRONTEND": "http://localhost:5173",
			"SERVICE_URL_DOCS": "http://127.0.0.1:3002",
			"BIND": "http://0.0.0.0:8080",
		},
		"jobs": {},
	}
	count(violations) == 0
}

test_no_violation_public_registries_and_docs if {
	violations := hardcoded_env_values.violations with input as {
		"env": {
			"NPM_REGISTRY": "https://registry.npmjs.org",
			"PYPI": "https://pypi.org/simple",
			"OPA_RELEASE": "https://github.com/open-policy-agent/opa/releases/download/v1.19.0/opa",
			"GHCR": "https://ghcr.io",
		},
		"jobs": {},
	}
	count(violations) == 0
}

# The anchored startswith test this replaces reported a URL that was already
# externalised, because the expression was not at position 0.
test_no_violation_url_with_embedded_expression if {
	violations := hardcoded_env_values.violations with input as {
		"env": {"API": "https://${{ vars.API_HOST }}/v1"},
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
