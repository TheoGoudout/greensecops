package greensecops.ci_workflow.security.overprovisioned_secrets_test

import data.greensecops.ci_workflow.security.overprovisioned_secrets as all_secrets
import rego.v1

test_violation_tojson_secrets_in_step_env if {
	violations := all_secrets.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "./deploy.sh", "env": {"ALL": "${{ toJSON(secrets) }}"}},
	]}}}
	count(violations) == 1
	some v in violations
	v.rule == "overprovisioned_secrets"
	v.job == "deploy"
}

test_violation_tojson_secrets_at_workflow_level if {
	violations := all_secrets.violations with input as {
		"env": {"ALL": "${{ toJSON(secrets) }}"},
		"jobs": {},
	}
	count(violations) == 1
	some v in violations
	v.job == null
}

# GitHub's expression functions are case-insensitive, and `to_json` is a valid
# spelling.
test_violation_alternate_spellings if {
	violations := all_secrets.violations with input as {"jobs": {
		"a": {"steps": [{"env": {"X": "${{ ToJson(secrets) }}"}}]},
		"b": {"steps": [{"env": {"X": "${{ to_json(secrets) }}"}}]},
	}}
	count(violations) == 2
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_named_secrets if {
	violations := all_secrets.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "./deploy.sh", "env": {"DEPLOY_TOKEN": "${{ secrets.DEPLOY_TOKEN }}"}},
	]}}}
	count(violations) == 0
}

# Serialising a different context is a readability question, not this one.
test_no_violation_tojson_of_another_context if {
	violations := all_secrets.violations with input as {"jobs": {"debug": {"steps": [
		{"env": {"CTX": "${{ toJSON(github) }}"}, "run": "echo \"$CTX\""},
	]}}}
	count(violations) == 0
}

test_no_violation_on_a_non_workflow_document if {
	violations := all_secrets.violations with input as {"compose_files": [{"path": "compose.yml"}]}
	count(violations) == 0
}
