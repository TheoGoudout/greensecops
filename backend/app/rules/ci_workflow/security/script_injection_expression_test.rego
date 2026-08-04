package greensecops.ci_workflow.security.script_injection_expression_test

import data.greensecops.ci_workflow.security.script_injection_expression as script_injection
import rego.v1

# Input is the parsed workflow YAML verbatim — no wrapper, and the bare `on:`
# key stays the string "on" because the evaluator parses with ruamel's YAML 1.2
# core schema.

_job(steps) := {"jobs": {"greet": {"runs-on": "ubuntu-latest", "steps": steps}}}

test_violation_for_a_pull_request_title if {
	violations := script_injection.violations with input as _job([{"run": "echo \"Thanks for ${{ github.event.pull_request.title }}\""}])
	count(violations) == 1
	some v in violations
	v.job == "greet"
	v.step_index == 0
}

test_violation_for_an_issue_comment_body if {
	violations := script_injection.violations with input as _job([{"run": "echo ${{ github.event.comment.body }}"}])
	count(violations) == 1
}

test_violation_for_the_head_ref_shorthand if {
	violations := script_injection.violations with input as _job([{"run": "git checkout ${{ github.head_ref }}"}])
	count(violations) == 1
}

test_violation_for_a_commit_message if {
	violations := script_injection.violations with input as _job([{"run": "echo ${{ github.event.head_commit.message }}"}])
	count(violations) == 1
}

test_violation_tolerates_whitespace_in_the_expression if {
	violations := script_injection.violations with input as _job([{"run": "echo ${{   github.event.issue.title   }}"}])
	count(violations) == 1
}

# The fix: the expression is substituted into the variable's *value*, so the
# shell never parses it as script.
test_no_violation_when_passed_through_env if {
	violations := script_injection.violations with input as {"jobs": {"greet": {
		"runs-on": "ubuntu-latest",
		"env": {"PR_TITLE": "${{ github.event.pull_request.title }}"},
		"steps": [{"run": "echo \"Thanks for $PR_TITLE\""}],
	}}}
	count(violations) == 0
}

# A pull request *number* is an integer GitHub controls, not free text.
test_no_violation_for_a_trusted_context if {
	violations := script_injection.violations with input as _job([{"run": "echo ${{ github.event.pull_request.number }}"}])
	count(violations) == 0
}

test_no_violation_for_a_secret_reference if {
	violations := script_injection.violations with input as _job([{"run": "deploy --token ${{ secrets.DEPLOY_TOKEN }}"}])
	count(violations) == 0
}

test_no_violation_for_a_plain_script if {
	violations := script_injection.violations with input as _job([{"run": "make build"}])
	count(violations) == 0
}

# A `uses:` step takes its input as data, not as script text.
test_no_violation_for_a_uses_step if {
	violations := script_injection.violations with input as _job([{
		"uses": "actions/github-script@v7",
		"with": {"script": "console.log(context.payload.pull_request.title)"},
	}])
	count(violations) == 0
}

test_each_offending_step_is_its_own_finding if {
	violations := script_injection.violations with input as _job([
		{"run": "echo ${{ github.event.pull_request.title }}"},
		{"run": "make build"},
		{"run": "echo ${{ github.event.pull_request.body }}"},
	])
	count(violations) == 2
	{v.step_index | some v in violations} == {0, 2}
}
