package greensecops.ci_workflow.security.bot_actor_spoofable_test

import data.greensecops.ci_workflow.security.bot_actor_spoofable as bot_check
import rego.v1

test_violation_job_if_on_actor if {
	violations := bot_check.violations with input as {"jobs": {"automerge": {
		"if": "github.actor == 'dependabot[bot]'",
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.rule == "bot_actor_spoofable"
	v.job == "automerge"
}

test_violation_triggering_actor if {
	violations := bot_check.violations with input as {"jobs": {"j": {
		"if": "github.triggering_actor == 'renovate[bot]'",
		"steps": [],
	}}}
	count(violations) == 1
}

test_violation_step_if_on_actor if {
	violations := bot_check.violations with input as {"jobs": {"j": {"steps": [
		{"name": "Merge", "if": "github.actor == 'github-actions[bot]'", "run": "gh pr merge"},
	]}}}
	count(violations) == 1
	some v in violations
	v.step_index == 0
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# The pull request's author is not chosen by whoever triggered the run.
test_no_violation_gating_on_pull_request_author if {
	violations := bot_check.violations with input as {"jobs": {"automerge": {
		"if": "github.event.pull_request.user.login == 'dependabot[bot]'",
		"steps": [],
	}}}
	count(violations) == 0
}

# An actor check that is not about a bot is a different question and not this
# rule's business.
test_no_violation_actor_check_without_a_bot_name if {
	violations := bot_check.violations with input as {"jobs": {"j": {
		"if": "github.actor != 'octocat'",
		"steps": [],
	}}}
	count(violations) == 0
}

test_no_violation_without_any_condition if {
	violations := bot_check.violations with input as {"jobs": {"j": {"steps": [{"run": "make"}]}}}
	count(violations) == 0
}

test_no_violation_on_a_non_workflow_document if {
	violations := bot_check.violations with input as {"dockerfiles": [{"path": "Dockerfile"}]}
	count(violations) == 0
}

# `!=` is a skip-guard: it runs the job for everyone *except* the bot, which is
# the opposite of trusting the name.
test_no_violation_for_a_skip_guard if {
	violations := bot_check.violations with input as {"jobs": {"b": {"if": "github.actor != 'dependabot[bot]'", "steps": [{"run": "make"}]}}}
	count(violations) == 0
}

test_no_violation_for_a_negated_contains if {
	violations := bot_check.violations with input as {"jobs": {"b": {"if": "!contains(github.actor, 'renovate')", "steps": [{"run": "make"}]}}}
	count(violations) == 0
}

test_violation_for_a_contains_gate if {
	violations := bot_check.violations with input as {"jobs": {"b": {"if": "contains(github.actor, 'dependabot')", "steps": [{"run": "make"}]}}}
	count(violations) == 1
}
