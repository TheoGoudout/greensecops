package greensecops.ci_workflow.security.typosquat_action_test

import data.greensecops.ci_workflow.security.typosquat_action as typosquat
import rego.v1

test_violation_singular_owner if {
	violations := typosquat.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "action/checkout@v4"},
	]}}}
	count(violations) == 1
	some v in violations
	v.rule == "typosquat_action"
	v.severity == "critical"
}

test_violation_unrelated_owner_of_a_distinctive_name if {
	violations := typosquat.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "evilcorp/upload-artifact@v4"},
	]}}}
	count(violations) == 1
}

# ─── Does not fire ───────────────────────────────────────────────────────────

test_no_violation_canonical_actions if {
	violations := typosquat.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
		{"uses": "astral-sh/setup-uv@v9"},
		{"uses": "oven-sh/setup-bun@v2"},
		{"uses": "docker/build-push-action@v6"},
		{"uses": "aws-actions/configure-aws-credentials@v5"},
		{"uses": "cloudflare/wrangler-action@v4"},
	]}}}
	count(violations) == 0
}

# A generic name has real third-party implementations; flagging them would be
# noise rather than signal, so generic names are not in the table at all.
test_no_violation_for_generic_names_with_real_alternatives if {
	violations := typosquat.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "buildjet/cache@v4"},
		{"uses": "Swatinem/rust-cache@v2"},
	]}}}
	count(violations) == 0
}

test_no_violation_for_a_local_reusable_workflow if {
	violations := typosquat.violations with input as {"jobs": {"call": {"steps": [
		{"uses": "./.github/actions/setup-node"},
	]}}}
	count(violations) == 0
}

test_no_violation_for_an_unrelated_action if {
	violations := typosquat.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "dorny/paths-filter@v3"},
	]}}}
	count(violations) == 0
}

test_no_violation_on_a_non_workflow_document if {
	violations := typosquat.violations with input as {"dockerfiles": [{"path": "Dockerfile"}]}
	count(violations) == 0
}
