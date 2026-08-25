package greensecops.ci_workflow.security.insecure_commands_enabled_test

import data.greensecops.ci_workflow.security.insecure_commands_enabled as rule
import rego.v1

test_violation_workflow_env if {
	violations := rule.violations with input as {
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": "true"},
		"jobs": {"build": {"steps": [{"run": "make"}]}},
	}
	count(violations) == 1
	some v in violations
	v.rule == "insecure_commands_enabled"
	v.job == null
}

test_violation_job_env if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": true},
		"steps": [{"run": "make"}],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "build"
}

test_violation_step_env if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [{
		"name": "Legacy build",
		"run": "./legacy-build.sh",
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": 1},
	}]}}}
	count(violations) == 1
	some v in violations
	v.step_index == 0
}

# The runner accepts more than "true"; so does this.
test_violation_yes_spelling if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": "YES"},
		"steps": [],
	}}}
	count(violations) == 1
}

# Each scope is its own finding — a workflow-level grant and a step-level one
# are two different lines to delete.
test_violation_reported_per_scope if {
	violations := rule.violations with input as {
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": "true"},
		"jobs": {"build": {
			"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": "true"},
			"steps": [{"run": "make", "env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": "true"}}],
		}},
	}
	count(violations) == 3
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_absent if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [{"run": "make"}]}}}
	count(violations) == 0
}

# Setting it to a falsy value leaves the commands disabled. Reporting that would
# be reporting someone for turning the feature off.
test_no_violation_explicitly_false if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": "false"},
		"steps": [],
	}}}
	count(violations) == 0
}

test_no_violation_zero if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS": 0},
		"steps": [],
	}}}
	count(violations) == 0
}

# A different variable that merely mentions the name is not the switch.
test_no_violation_similar_key if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"ACTIONS_ALLOW_UNSECURE_COMMANDS_LEGACY": "true"},
		"steps": [],
	}}}
	count(violations) == 0
}
