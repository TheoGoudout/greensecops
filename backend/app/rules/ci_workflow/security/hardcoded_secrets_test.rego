package greensecops.ci_workflow.security.hardcoded_secrets_test

import data.greensecops.ci_workflow.security.hardcoded_secrets
import rego.v1

# ─── Fires ───────────────────────────────────────────────────────────────────

test_violation_high_entropy_literal_under_secret_name if {
	violations := hardcoded_secrets.violations with input as {
		"env": {"API_KEY": "sk-prod-abc123def456"},
		"jobs": {},
	}
	count(violations) == 1
	some v in violations
	v.rule == "hardcoded_secrets"
	v.severity == "critical"
	v.job == null
}

# A recognised credential format needs no help from the variable name.
test_violation_known_credential_format_under_any_name if {
	violations := hardcoded_secrets.violations with input as {
		"env": {"HARMLESS_LOOKING": "AKIAIOSFODNN7EXAMPLE"},
		"jobs": {},
	}
	count(violations) == 1
}

test_violation_in_job_env if {
	violations := hardcoded_secrets.violations with input as {"jobs": {"deploy": {
		"env": {"DEPLOY_TOKEN": "ghp_16C7e42F292c6912E7710c838347Ae178B4a"},
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
}

# The step-level clause existed but had no test.
test_violation_in_step_env if {
	violations := hardcoded_secrets.violations with input as {"jobs": {"deploy": {"steps": [{
		"name": "Push",
		"run": "./push.sh",
		"env": {"REGISTRY_PASSWORD": "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHNlY3JldA=="},
	}]}}}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
	contains(v.message, "step 'Push'")
}

# ─── Does not fire: the false positives this rework exists to remove ──────────

# These are the exact values in this repository's test-backend,
# test-docker-compose and playwright workflows. They seed throwaway containers
# that live for the length of one job. Reporting them at critical — and
# "fixing" them into undefined ${{ secrets.* }} that evaluate to empty strings —
# broke CI in PR #220.
test_no_violation_ci_fixture_placeholders if {
	violations := hardcoded_secrets.violations with input as {"jobs": {"test": {
		"env": {
			"SERVICE_PASSWORD_POSTGRES": "testpassword",
			"SERVICE_PASSWORD_FIRSTSUPERUSER": "testpassword",
			"SECRET_KEY": "changethischangethischangethischangethischangethischangethischanget",
			"POSTGRES_PASSWORD": "testpassword",
		},
		"steps": [],
	}}}
	count(violations) == 0
}

test_no_violation_secret_ref if {
	violations := hardcoded_secrets.violations with input as {
		"env": {"API_KEY": "${{ secrets.MY_API_KEY }}"},
		"jobs": {},
	}
	count(violations) == 0
}

# The old two-prefix startswith test treated both of these as hardcoded.
test_no_violation_secret_ref_without_space_or_at_offset if {
	violations := hardcoded_secrets.violations with input as {
		"env": {
			"API_KEY": "${{secrets.MY_API_KEY}}",
			"AUTH_HEADER": "Bearer ${{ secrets.TOKEN }}",
		},
		"jobs": {},
	}
	count(violations) == 0
}

test_no_violation_vars_and_other_contexts if {
	violations := hardcoded_secrets.violations with input as {
		"env": {
			"PASSWORD": "${{ vars.DB_PASSWORD }}",
			"TOKEN": "${{ github.token }}",
			"OTHER": "${{ inputs.token }}",
		},
		"jobs": {},
	}
	count(violations) == 0
}

# Named like a secret, but the value is plainly not one.
test_no_violation_non_secret_values_under_secret_names if {
	violations := hardcoded_secrets.violations with input as {
		"env": {
			"TOKEN_FILE": "/tmp/token",
			"SECRET_NAME": "my-k8s-secret",
			"HAS_TOKEN": "false",
			"PASSWORD_MIN_LENGTH": "12",
		},
		"jobs": {},
	}
	count(violations) == 0
}

test_no_violation_unrelated_env_var if {
	violations := hardcoded_secrets.violations with input as {
		"env": {"NODE_ENV": "production"},
		"jobs": {},
	}
	count(violations) == 0
}

# ─── Shape ───────────────────────────────────────────────────────────────────

# Two secrets at one (job, step_index) must produce two issues, which needs the
# discriminator — the dedup key is (workflow, rule, job, step_index,
# discriminator).
test_each_env_var_is_its_own_finding if {
	violations := hardcoded_secrets.violations with input as {
		"env": {
			"API_KEY": "sk-prod-abc123def456",
			"DEPLOY_TOKEN": "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
		},
		"jobs": {},
	}
	count(violations) == 2
	{v.discriminator | some v in violations} == {"API_KEY", "DEPLOY_TOKEN"}
}
