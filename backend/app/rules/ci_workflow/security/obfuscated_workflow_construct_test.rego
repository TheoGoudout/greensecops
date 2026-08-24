package greensecops.ci_workflow.security.obfuscated_workflow_construct_test

import data.greensecops.ci_workflow.security.obfuscated_workflow_construct as rule
import rego.v1

test_violation_double_separator_in_uses if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions//checkout@v4"},
	]}}}
	count(violations) == 1
	some v in violations
	v.rule == "obfuscated_workflow_construct"
}

test_violation_dot_segment_in_uses if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/./checkout@v4"},
	]}}}
	count(violations) == 1
}

test_violation_parent_traversal_in_uses if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout/../checkout@v4"},
	]}}}
	count(violations) == 1
}

test_violation_bracket_index_expression if {
	violations := rule.violations with input as {"jobs": {"triage": {"steps": [
		{"run": "echo \"${{ github['event']['issue']['title'] }}\""},
	]}}}
	count(violations) == 1
	some v in violations
	v.step_index == 0
}

test_violation_bracket_index_on_secrets if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "./x.sh", "env": {"K": "${{ secrets['API_KEY'] }}"}},
	]}}}
	count(violations) == 1
}

test_violation_noop_roundtrip if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "echo ${{ fromJSON(toJSON(github.event.pull_request.title)) }}"},
	]}}}
	count(violations) == 1
}

test_violation_job_if if {
	violations := rule.violations with input as {"jobs": {"build": {
		"if": "${{ github['event_name'] == 'push' }}",
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "build"
	not v.step_index
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_plain_uses if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"},
	]}}}
	count(violations) == 0
}

# A local reusable workflow genuinely begins "./".
test_no_violation_local_ref if {
	violations := rule.violations with input as {"jobs": {"call": {"uses": "./.github/workflows/reusable.yml", "steps": [
		{"uses": "./.github/actions/setup"},
	]}}}
	count(violations) == 0
}

# "docker://" is a scheme; the "//" in it is not a redundant separator.
test_no_violation_docker_ref if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "docker://alpine:3.20"},
	]}}}
	count(violations) == 0
}

test_no_violation_dotted_expression if {
	violations := rule.violations with input as {"jobs": {"triage": {"steps": [
		{"run": "echo \"$TITLE\"", "env": {"TITLE": "${{ github.event.issue.title }}"}},
	]}}}
	count(violations) == 0
}

# Dynamic indexing has no dotted equivalent — it is the only way to write the
# lookup, so it is not evasion.
test_no_violation_dynamic_index if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "./x.sh", "env": {"K": "${{ secrets[format('TOKEN_{0}', matrix.env)] }}"}},
	]}}}
	count(violations) == 0
}

test_no_violation_dynamic_index_by_context if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "./x.sh", "env": {"K": "${{ secrets[matrix.secret_name] }}"}},
	]}}}
	count(violations) == 0
}

# A shell associative-array read is not a GitHub expression, and looking outside
# the `${{ }}` would report it.
test_no_violation_shell_array_subscript if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "declare -A config; config['name']=x; echo \"${config['name']}\""},
	]}}}
	count(violations) == 0
}

# fromJSON on its own is ordinary matrix plumbing; only the round trip is a no-op.
test_no_violation_plain_fromjson if {
	violations := rule.violations with input as {"jobs": {"build": {
		"strategy": {"matrix": {"include": "${{ fromJSON(needs.setup.outputs.matrix) }}"}},
		"steps": [{"run": "make"}],
	}}}
	count(violations) == 0
}
