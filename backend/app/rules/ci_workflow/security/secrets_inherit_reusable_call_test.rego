package greensecops.ci_workflow.security.secrets_inherit_reusable_call_test

import data.greensecops.ci_workflow.security.secrets_inherit_reusable_call as secrets_inherit
import rego.v1

_CALLEE := "my-org/workflows/.github/workflows/deploy.yml@main"

test_violation_for_secrets_inherit if {
	violations := secrets_inherit.violations with input as {"jobs": {"deploy": {
		"uses": _CALLEE,
		"secrets": "inherit",
	}}}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
	v.step == _CALLEE
}

test_violation_is_case_insensitive if {
	violations := secrets_inherit.violations with input as {"jobs": {"deploy": {
		"uses": _CALLEE,
		"secrets": "Inherit",
	}}}
	count(violations) == 1
}

# The fix: name the secrets, so the call site documents the exposure.
test_no_violation_for_named_secrets if {
	violations := secrets_inherit.violations with input as {"jobs": {"deploy": {
		"uses": _CALLEE,
		"secrets": {"DEPLOY_TOKEN": "${{ secrets.DEPLOY_TOKEN }}"},
	}}}
	count(violations) == 0
}

test_no_violation_when_no_secrets_are_passed if {
	violations := secrets_inherit.violations with input as {"jobs": {"deploy": {"uses": _CALLEE}}}
	count(violations) == 0
}

# A normal job that happens to have steps is not a reusable-workflow call.
test_no_violation_for_a_steps_job if {
	violations := secrets_inherit.violations with input as {"jobs": {"build": {
		"runs-on": "ubuntu-latest",
		"steps": [{"run": "make build"}],
	}}}
	count(violations) == 0
}

test_each_inheriting_call_is_its_own_finding if {
	violations := secrets_inherit.violations with input as {"jobs": {
		"deploy": {"uses": _CALLEE, "secrets": "inherit"},
		"notify": {"uses": "my-org/workflows/.github/workflows/notify.yml@main", "secrets": "inherit"},
		"lint": {"uses": "my-org/workflows/.github/workflows/lint.yml@main"},
	}}
	count(violations) == 2
	{v.discriminator | some v in violations} == {"deploy", "notify"}
}
