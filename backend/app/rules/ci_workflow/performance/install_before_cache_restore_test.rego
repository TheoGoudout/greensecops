package greensecops.ci_workflow.performance.install_before_cache_restore_test

import data.greensecops.ci_workflow.performance.install_before_cache_restore as bad_order
import rego.v1

_workflow(steps) := {"jobs": {"build": {
	"runs-on": "ubuntu-latest",
	"steps": steps,
	"__start_line__": 4,
	"__end_line__": 20,
}}}

_cache := {
	"uses": "actions/cache@v4",
	"with": {"path": "~/.npm", "key": "npm-abc"},
	"__start_line__": 8,
	"__end_line__": 12,
}

_install := {"run": "npm ci", "__start_line__": 6, "__end_line__": 6}

test_violation_when_the_cache_comes_after_the_install if {
	violations := bad_order.violations with input as _workflow([_install, _cache])
	count(violations) == 1
	some v in violations
	v.job == "build"
	v.category == "performance"
}

test_no_violation_when_the_cache_comes_first if {
	violations := bad_order.violations with input as _workflow([_cache, _install])
	count(violations) == 0
}

test_violation_for_a_python_install if {
	violations := bad_order.violations with input as _workflow([
		{"run": "pip install -r requirements.txt"},
		_cache,
	])
	count(violations) == 1
}

test_no_violation_without_a_cache_step if {
	violations := bad_order.violations with input as _workflow([_install])
	count(violations) == 0
}

test_no_violation_without_an_install_step if {
	violations := bad_order.violations with input as _workflow([_cache, {"run": "npm test"}])
	count(violations) == 0
}

# The setup actions cache internally and get the ordering right by
# construction, so they are not what this rule looks at.
test_no_violation_for_a_setup_action_with_caching if {
	violations := bad_order.violations with input as _workflow([
		{"uses": "actions/setup-node@v4", "with": {"cache": "npm"}},
		_install,
	])
	count(violations) == 0
}

test_the_message_names_both_step_positions if {
	violations := bad_order.violations with input as _workflow([_install, _cache])
	some v in violations
	contains(v.message, "step 1")
	contains(v.message, "step 0")
}

test_the_finding_points_at_the_cache_step if {
	violations := bad_order.violations with input as _workflow([_install, _cache])
	some v in violations
	v.line_start == 8
	v.step_index == 1
}
