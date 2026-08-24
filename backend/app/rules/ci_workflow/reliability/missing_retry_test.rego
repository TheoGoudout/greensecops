package greensecops.ci_workflow.reliability.missing_retry_test

import data.greensecops.ci_workflow.reliability.missing_retry
import rego.v1

test_violation_curl_without_retry if {
	violations := missing_retry.violations with input as {"jobs": {"fetch": {"steps": [{"run": "curl https://example.com/data.json -o data.json"}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "missing_retry"
	v.step_index == 0
}

test_violation_wget_without_retry if {
	violations := missing_retry.violations with input as {"jobs": {"setup": {"steps": [{"run": "wget https://example.com/installer.sh"}]}}}
	count(violations) == 1
}

# Package managers retry internally — npm's fetch-retries defaults to 2, pip's
# --retries to 5 — so asking the author to wrap them duplicates the tool's own
# behaviour. Demanding it here also made examples/deploy.yml, the reference
# workflow that must stay violation-free, trip this rule.
test_no_violation_for_package_managers_that_retry_internally if {
	violations := missing_retry.violations with input as {"jobs": {
		"node": {"steps": [{"run": "npm ci && npm run build"}]},
		"python": {"steps": [{"run": "pip install -r requirements.txt"}]},
		"system": {"steps": [{"run": "apt-get update && apt-get install -y jq"}]},
	}}
	count(violations) == 0
}

test_no_violation_retry_action_in_job if {
	violations := missing_retry.violations with input as {"jobs": {"fetch": {"steps": [
		{"run": "curl -o tool https://example.com/tool"},
		{"uses": "nick-fields/retry@v3", "with": {"command": "curl -o tool https://example.com/tool"}},
	]}}}
	count(violations) == 0
}

test_no_violation_no_network_commands if {
	violations := missing_retry.violations with input as {"jobs": {"lint": {"steps": [{"run": "eslint ."}]}}}
	count(violations) == 0
}

# ─── The false positives this rework exists to remove ─────────────────────────

# curl and wget have retry built in; the old rule did not recognise either, so a
# step that already handled transient failure was still reported.
test_no_violation_curl_own_retry_flag if {
	violations := missing_retry.violations with input as {"jobs": {"fetch": {"steps": [
		{"run": "curl -fsSL --retry 3 --retry-connrefused -o tool https://example.com/tool"},
	]}}}
	count(violations) == 0
}

test_no_violation_wget_tries if {
	violations := missing_retry.violations with input as {"jobs": {"fetch": {"steps": [
		{"run": "wget --tries=5 https://example.com/tool"},
	]}}}
	count(violations) == 0
}

test_no_violation_hand_rolled_retry_loop if {
	violations := missing_retry.violations with input as {"jobs": {"fetch": {"steps": [{"run": concat("\n", [
		"for i in 1 2 3; do",
		"  curl -fsSL -o tool https://example.com/tool && break",
		"  sleep 5",
		"done",
	])}]}}}
	count(violations) == 0
}

# A comment is not a command. The old rule matched the raw block, so both of
# these counted as unretried network steps.
test_no_violation_network_command_only_in_a_comment if {
	violations := missing_retry.violations with input as {"jobs": {"build": {"steps": [
		{"run": "# we curl the API in a later job\nmake build"},
	]}}}
	count(violations) == 0
}

# `apt-get-wrapper.sh` is not `apt-get`.
test_no_violation_substring_of_a_command_name if {
	violations := missing_retry.violations with input as {"jobs": {"build": {"steps": [
		{"run": "./scripts/apt-get-wrapper.sh --offline"},
	]}}}
	count(violations) == 0
}

# ─── Shape ───────────────────────────────────────────────────────────────────

# The finding now points at the offending step rather than the whole job, so two
# unretried downloads are two findings at distinct step indexes.
test_each_unretried_step_is_its_own_finding if {
	violations := missing_retry.violations with input as {"jobs": {"fetch": {"steps": [
		{"run": "curl -o a https://example.com/a"},
		{"run": "echo unrelated"},
		{"run": "wget https://example.com/b"},
	]}}}
	count(violations) == 2
	{v.step_index | some v in violations} == {0, 2}
}
