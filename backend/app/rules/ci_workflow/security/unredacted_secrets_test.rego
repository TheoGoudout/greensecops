package greensecops.ci_workflow.security.unredacted_secrets_test

import data.greensecops.ci_workflow.security.unredacted_secrets as rule
import rego.v1

test_violation_step_env_field_access if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [{
		"name": "Deploy",
		"run": "./deploy.sh",
		"env": {"DB_PASSWORD": "${{ fromJSON(secrets.DB_CREDENTIALS).password }}"},
	}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "unredacted_secrets"
	v.step_index == 0
}

# GitHub's expression functions are case-insensitive and both spellings are in
# the wild.
test_violation_lowercase_spelling if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "echo ${{ fromJson(secrets.CREDS).token }}"},
	]}}}
	count(violations) == 1
}

test_violation_in_with_input if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [{
		"uses": "some/action@v1",
		"with": {"token": "${{ fromJSON(secrets.BUNDLE).api_key }}"},
	}]}}}
	count(violations) == 1
}

test_violation_job_env if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"env": {"PW": "${{ fromJSON(secrets.CREDS).password }}"},
		"steps": [{"run": "./deploy.sh"}],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
	not v.step_index
}

test_violation_workflow_env if {
	violations := rule.violations with input as {
		"env": {"PW": "${{ fromJSON(secrets.CREDS).password }}"},
		"jobs": {"deploy": {"steps": [{"run": "./deploy.sh"}]}},
	}
	count(violations) == 1
	some v in violations
	v.job == null
}

# A job-level binding is one line of YAML. Reporting it again for each step that
# merely inherits it would count the same line N times.
test_job_env_reported_once_not_per_step if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"env": {"PW": "${{ fromJSON(secrets.CREDS).password }}"},
		"steps": [{"run": "a"}, {"run": "b"}, {"run": "c"}],
	}}}
	count(violations) == 1
}

# But a step that parses a secret itself is its own finding, even inside a job
# that already has one.
test_step_with_own_parse_still_reported if {
	violations := rule.violations with input as {"jobs": {"deploy": {
		"env": {"PW": "${{ fromJSON(secrets.CREDS).password }}"},
		"steps": [
			{"run": "a"},
			{"run": "echo ${{ fromJSON(secrets.OTHER).token }}"},
		],
	}}}
	count(violations) == 2
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# The whole secret, passed straight through. This is the shape the fix produces,
# and the runner masks it.
test_no_violation_direct_secret_reference if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [{
		"run": "./deploy.sh",
		"env": {"DB_PASSWORD": "${{ secrets.DB_PASSWORD }}"},
	}]}}}
	count(violations) == 0
}

# fromJSON over something that is not a secret is ordinary matrix/config work.
test_no_violation_fromjson_of_non_secret if {
	violations := rule.violations with input as {"jobs": {"build": {
		"strategy": {"matrix": {"include": "${{ fromJSON(needs.setup.outputs.matrix) }}"}},
		"steps": [{"run": "make"}],
	}}}
	count(violations) == 0
}

test_no_violation_fromjson_of_vars if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "echo ${{ fromJSON(vars.CONFIG).region }}"},
	]}}}
	count(violations) == 0
}

# `toJSON(secrets)` is `overprovisioned_secrets`' finding, not this one. Two
# findings on one line is noise however true each is.
test_no_violation_tojson_secrets_belongs_to_other_rule if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "./x.sh", "env": {"ALL": "${{ toJSON(secrets) }}"}},
	]}}}
	count(violations) == 0
}
