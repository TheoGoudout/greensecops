package greensecops.ci_workflow.security.workflow_env_holds_secret_test

import data.greensecops.ci_workflow.security.workflow_env_holds_secret as env_holds_secret
import rego.v1

_publish_steps := [{"uses": "actions/checkout@v5"}, {"run": "npm publish"}]

test_violation_for_a_workflow_level_secret if {
	violations := env_holds_secret.violations with input as {
		"env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
		"jobs": {"publish": {"steps": _publish_steps}},
	}
	count(violations) == 1
	some v in violations
	v.context == "NPM_TOKEN"
}

test_violation_for_a_job_level_secret if {
	violations := env_holds_secret.violations with input as {"jobs": {"publish": {
		"env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
		"steps": _publish_steps,
	}}}
	count(violations) == 1
	some v in violations
	v.job == "publish"
}

# The fix: bound on the one step that needs it, which this rule does not reach.
test_no_violation_for_a_step_level_secret if {
	violations := env_holds_secret.violations with input as {"jobs": {"publish": {"steps": [
		{"uses": "actions/checkout@v5"},
		{"run": "npm publish", "env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"}},
	]}}}
	count(violations) == 0
}

test_no_violation_for_a_non_secret_env_value if {
	violations := env_holds_secret.violations with input as {
		"env": {"NODE_ENV": "production", "REGISTRY": "https://registry.npmjs.org"},
		"jobs": {"publish": {"steps": _publish_steps}},
	}
	count(violations) == 0
}

# A github.* expression is not a secret.
test_no_violation_for_a_context_expression if {
	violations := env_holds_secret.violations with input as {
		"env": {"SHA": "${{ github.sha }}"},
		"jobs": {"publish": {"steps": _publish_steps}},
	}
	count(violations) == 0
}

test_no_violation_when_no_env_is_declared if {
	violations := env_holds_secret.violations with input as {"jobs": {"publish": {"steps": _publish_steps}}}
	count(violations) == 0
}

test_each_exposed_secret_is_its_own_finding if {
	violations := env_holds_secret.violations with input as {
		"env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}", "AWS_KEY": "${{ secrets.AWS_KEY }}"},
		"jobs": {"publish": {"steps": _publish_steps}},
	}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}

# Workflow-level and job-level bindings of the same name are distinct findings
# with distinct blast radii.
test_workflow_and_job_level_are_separate_findings if {
	violations := env_holds_secret.violations with input as {
		"env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
		"jobs": {"publish": {
			"env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
			"steps": _publish_steps,
		}},
	}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
