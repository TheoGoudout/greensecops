package greensecops.ci_workflow.reliability.unsound_ternary_test

import data.greensecops.ci_workflow.reliability.unsound_ternary as rule
import rego.v1

test_violation_empty_true_arm_in_env if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [{
		"run": "./test.sh",
		"env": {"VERBOSE": "${{ github.event_name == 'push' && '' || '--quiet' }}"},
	}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "unsound_ternary"
	v.step_index == 0
}

test_violation_false_true_arm if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"if": "${{ github.ref == 'refs/heads/main' && false || true }}", "run": "x"},
	]}}}
	count(violations) == 1
}

test_violation_zero_true_arm if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"run": "x", "env": {"N": "${{ inputs.fast && 0 || 5 }}"}},
	]}}}
	count(violations) == 1
}

test_violation_null_true_arm if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"run": "x", "env": {"N": "${{ inputs.fast && null || 'v' }}"}},
	]}}}
	count(violations) == 1
}

test_violation_double_quoted_empty if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"run": "x", "env": {"N": "${{ inputs.fast && \"\" || 'v' }}"}},
	]}}}
	count(violations) == 1
}

test_violation_job_level_env if {
	violations := rule.violations with input as {"jobs": {"test": {
		"env": {"FLAG": "${{ github.event_name == 'push' && '' || '--quiet' }}"},
		"steps": [{"run": "./test.sh"}],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "test"
	not v.step_index
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# A truthy true-arm is the idiom working as intended.
test_no_violation_truthy_true_arm if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"run": "x", "env": {"V": "${{ github.event_name == 'push' && '--verbose' || '--quiet' }}"}},
	]}}}
	count(violations) == 0
}

test_no_violation_plain_boolean_condition if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"if": "${{ success() && github.ref == 'refs/heads/main' }}", "run": "x"},
	]}}}
	count(violations) == 0
}

# Shell `&& false ||` is ordinary control flow, not a GitHub expression, and
# looking outside the `${{ }}` would report it.
test_no_violation_shell_and_or if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"run": "test -f x && false || echo missing"},
	]}}}
	count(violations) == 0
}

# A falsy value in the *false* position is fine — that arm is the fallback.
test_no_violation_falsy_false_arm if {
	violations := rule.violations with input as {"jobs": {"test": {"steps": [
		{"run": "x", "env": {"V": "${{ inputs.debug && '--debug' || '' }}"}},
	]}}}
	count(violations) == 0
}

# The job clause must not double-report what the step clause already found.
test_step_hit_suppresses_job_clause if {
	violations := rule.violations with input as {"jobs": {"test": {
		"env": {"A": "${{ inputs.x && '' || 'y' }}"},
		"steps": [{"run": "x", "env": {"B": "${{ inputs.x && '' || 'y' }}"}}],
	}}}
	count(violations) == 1
	some v in violations
	v.step_index == 0
}
