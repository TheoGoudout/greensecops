package greensecops.ci_workflow.reliability.continue_on_error_abuse_test

import data.greensecops.ci_workflow.reliability.continue_on_error_abuse as coe
import rego.v1

test_violation_step_with_continue_on_error if {
	violations := coe.violations with input as {"jobs": {"build": {"steps": [{
		"name": "Flaky step",
		"run": "some-flaky-command",
		"continue-on-error": true,
	}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "continue_on_error_abuse"
	v.job == "build"
}

test_no_violation_no_continue_on_error if {
	violations := coe.violations with input as {"jobs": {"build": {"steps": [{"name": "Build", "run": "make build"}]}}}
	count(violations) == 0
}

test_no_violation_continue_on_error_false if {
	violations := coe.violations with input as {"jobs": {"build": {"steps": [{
		"name": "Safe step",
		"run": "echo hi",
		"continue-on-error": false,
	}]}}}
	count(violations) == 0
}

# The inline comment in the rule warns that a bare `step.uses` in an
# `object.get` default makes the rule undefined for run-only steps; this pins it.
test_violation_on_a_run_only_step_without_a_name if {
	violations := coe.violations with input as {"jobs": {"build": {"steps": [{
		"run": "make",
		"continue-on-error": true,
	}]}}}
	count(violations) == 1
	some v in violations
	contains(v.message, "unnamed step")
}

# ─── The false positives this rework exists to remove ─────────────────────────

# The legitimate pattern: swallow the failure, then act on it. The old rule had
# no way to see this, and its own fix text asked for a comment it could not read.
test_no_violation_when_outcome_is_consumed if {
	violations := coe.violations with input as {"jobs": {"ci": {"steps": [
		{"name": "Run tests", "id": "tests", "run": "npm test", "continue-on-error": true},
		{"name": "Report", "if": "steps.tests.outcome == 'failure'", "run": "./report.sh"},
	]}}}
	count(violations) == 0
}

test_no_violation_when_conclusion_is_consumed if {
	violations := coe.violations with input as {"jobs": {"ci": {"steps": [
		{"id": "scan", "run": "scan", "continue-on-error": true},
		{"run": "echo ${{ steps.scan.conclusion }}"},
	]}}}
	count(violations) == 0
}

# Failing a build because a coverage service was briefly down helps nobody.
test_no_violation_for_best_effort_uploads if {
	violations := coe.violations with input as {"jobs": {"ci": {"steps": [
		{"uses": "codecov/codecov-action@v4", "continue-on-error": true},
		{"uses": "actions/upload-artifact@v4", "continue-on-error": true},
	]}}}
	count(violations) == 0
}

# An id alone is not enough — nothing reads it, so the failure is still silent.
test_violation_when_step_has_an_id_nobody_reads if {
	violations := coe.violations with input as {"jobs": {"ci": {"steps": [
		{"id": "tests", "run": "npm test", "continue-on-error": true},
		{"run": "echo unrelated"},
	]}}}
	count(violations) == 1
}
