package greensecops.ci_workflow.security.github_env_injection_test

import data.greensecops.ci_workflow.security.github_env_injection as env_inj
import rego.v1

test_violation_expanded_value_into_github_env if {
	violations := env_inj.violations with input as {"jobs": {"label": {
		"env": {"PR_TITLE": "${{ github.event.pull_request.title }}"},
		"steps": [{"run": "echo \"TITLE=$PR_TITLE\" >> \"$GITHUB_ENV\""}],
	}}}
	count(violations) == 1
	some v in violations
	v.rule == "github_env_injection"
	v.severity == "high"
	v.step_index == 0
}

test_violation_github_path if {
	violations := env_inj.violations with input as {"jobs": {"build": {"steps": [
		{"run": "echo \"$TOOL_DIR\" >> $GITHUB_PATH"},
	]}}}
	count(violations) == 1
}

test_violation_braced_form if {
	violations := env_inj.violations with input as {"jobs": {"build": {"steps": [
		{"run": "echo \"VER=${VERSION}\" >> ${GITHUB_ENV}"},
	]}}}
	count(violations) == 1
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# A constant is not attacker-controlled; there is nothing to inject.
test_no_violation_literal_value if {
	violations := env_inj.violations with input as {"jobs": {"build": {"steps": [
		{"run": "echo \"CI=true\" >> $GITHUB_ENV"},
	]}}}
	count(violations) == 0
}

test_no_violation_reading_the_env_file if {
	violations := env_inj.violations with input as {"jobs": {"build": {"steps": [
		{"run": "cat $GITHUB_ENV"},
	]}}}
	count(violations) == 0
}

# $GITHUB_OUTPUT is length-delimited when written with a heredoc and is the
# recommended alternative, so it is not this rule's business.
test_no_violation_github_output if {
	violations := env_inj.violations with input as {"jobs": {"build": {"steps": [
		{"run": "echo \"tag=$TAG\" >> $GITHUB_OUTPUT"},
	]}}}
	count(violations) == 0
}

test_no_violation_step_without_run if {
	violations := env_inj.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
	]}}}
	count(violations) == 0
}

# The rule must be silent on a document from another engine — every engine's
# rules compile together, and a rule keyed on a missing field fires on all of
# them.
test_no_violation_on_a_non_workflow_document if {
	violations := env_inj.violations with input as {"resource": [{"aws_s3_bucket": {"b": {}}}]}
	count(violations) == 0
}

# Runner-supplied values cannot carry a newline, so writing one is not an
# injection. This was the single largest false positive in the rule.
test_no_violation_for_a_github_controlled_variable if {
	violations := env_inj.violations with input as {"jobs": {"b": {"steps": [{"run": "echo \"SHA=$GITHUB_SHA\" >> \"$GITHUB_ENV\""}]}}}
	count(violations) == 0
}

test_no_violation_for_runner_os if {
	violations := env_inj.violations with input as {"jobs": {"b": {"steps": [{"run": "echo \"OS=${RUNNER_OS}\" >> $GITHUB_ENV"}]}}}
	count(violations) == 0
}

test_no_violation_for_home if {
	violations := env_inj.violations with input as {"jobs": {"b": {"steps": [{"run": "echo \"BIN=$HOME/bin\" >> $GITHUB_PATH"}]}}}
	count(violations) == 0
}

# The case the rule exists for is untouched.
test_violation_for_an_untrusted_value_still_fires if {
	violations := env_inj.violations with input as {"jobs": {"b": {"steps": [{"run": "echo \"T=$PR_TITLE\" >> $GITHUB_ENV"}]}}}
	count(violations) == 1
}

test_violation_when_a_trusted_and_an_untrusted_name_share_a_line if {
	violations := env_inj.violations with input as {"jobs": {"b": {"steps": [{"run": "echo \"K=$GITHUB_SHA-$PR_TITLE\" >> $GITHUB_ENV"}]}}}
	count(violations) == 1
}
