package greensecops.ci_workflow.energy.redundant_steps_test

import data.greensecops.ci_workflow.energy.redundant_steps
import rego.v1

_build_job := {"steps": [{"uses": "docker/build-push-action@v6"}]}

test_violation_expensive_build_in_three_jobs if {
	violations := redundant_steps.violations with input as {"jobs": {
		"amd64": _build_job,
		"arm64": _build_job,
		"scan": _build_job,
	}}
	count(violations) == 1
	some v in violations
	v.rule == "redundant_steps"
	v.job == null
	v.discriminator == "docker/build-push-action"
}

# One finding per action, not one per step occurrence. The old rule emitted six
# identical findings for a six-job workflow.
test_one_finding_per_action_not_per_step if {
	violations := redundant_steps.violations with input as {"jobs": {
		"a": _build_job,
		"b": _build_job,
		"c": _build_job,
		"d": _build_job,
		"e": _build_job,
		"f": _build_job,
	}}
	count(violations) == 1
}

test_no_violation_in_two_jobs if {
	violations := redundant_steps.violations with input as {"jobs": {"a": _build_job, "b": _build_job}}
	count(violations) == 0
}

# The false positive this rework exists to remove. Every job runs on a fresh
# runner with an empty workspace, so checkout and toolchain setup have to repeat
# — the old rule made that a finding, which no multi-job workflow could satisfy.
test_no_violation_for_setup_actions_that_must_repeat if {
	setup_job := {"steps": [
		{"uses": "actions/checkout@v4"},
		{"uses": "actions/setup-node@v4"},
		{"uses": "actions/cache@v4"},
		{"uses": "docker/login-action@v3"},
		{"uses": "aws-actions/configure-aws-credentials@v5"},
	]}
	violations := redundant_steps.violations with input as {"jobs": {
		"test": setup_job,
		"lint": setup_job,
		"build": setup_job,
		"deploy": setup_job,
	}}
	count(violations) == 0
}

test_no_violation_when_no_steps_use_actions if {
	violations := redundant_steps.violations with input as {"jobs": {
		"a": {"steps": [{"run": "make"}]},
		"b": {"steps": [{"run": "make"}]},
		"c": {"steps": [{"run": "make"}]},
	}}
	count(violations) == 0
}

test_distinct_expensive_actions_are_separate_findings if {
	mixed := {"steps": [
		{"uses": "docker/build-push-action@v6"},
		{"uses": "gradle/gradle-build-action@v3"},
	]}
	violations := redundant_steps.violations with input as {"jobs": {"a": mixed, "b": mixed, "c": mixed}}
	count(violations) == 2
	{v.discriminator | some v in violations} == {"docker/build-push-action", "gradle/gradle-build-action"}
}
