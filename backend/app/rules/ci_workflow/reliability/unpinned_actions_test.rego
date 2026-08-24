package greensecops.ci_workflow.reliability.unpinned_actions_test

import data.greensecops.ci_workflow.reliability.unpinned_actions
import rego.v1

_step(uses) := {"jobs": {"build": {"steps": [{"uses": uses}]}}}

test_violation_branch_ref if {
	count(unpinned_actions.violations) == 1 with input as _step("some-org/action@main")
}

test_violation_bare_major_tag if {
	count(unpinned_actions.violations) == 1 with input as _step("actions/checkout@v4")
}

# The case `untrusted_actions` caught and this rule used to miss.
test_violation_third_party_semver_tag if {
	count(unpinned_actions.violations) == 1 with input as _step("some-org/action@v2.1.0")
}

# The case neither rule caught: a first-party action on a full semver tag.
test_violation_first_party_semver_tag if {
	count(unpinned_actions.violations) == 1 with input as _step("actions/checkout@v4.1.1")
}

test_violation_no_ref_at_all if {
	violations := unpinned_actions.violations with input as _step("some-org/action")
	count(violations) == 1
	some v in violations
	contains(v.message, "the default branch")
}

test_no_violation_sha_pinned if {
	count(unpinned_actions.violations) == 0 with input as _step("some-org/action@a81bbbf8298c0fa03ea29cdc473d45769f953675")
}

test_no_violation_first_party_sha_pinned if {
	count(unpinned_actions.violations) == 0 with input as _step("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
}

# A local composite action cannot be pinned to a commit at all — the old
# `untrusted_actions` reported every one of them at high severity.
test_no_violation_local_action if {
	count(unpinned_actions.violations) == 0 with input as _step("./.github/actions/setup")
}

test_no_violation_local_reusable_workflow if {
	count(unpinned_actions.violations) == 0 with input as _step("./.github/workflows/build.yml")
}

# "Pin to a commit SHA" is not advice a Docker action can act on.
test_no_violation_docker_ref if {
	count(unpinned_actions.violations) == 0 with input as _step("docker://alpine:3.20")
}

test_no_violation_run_step if {
	count(unpinned_actions.violations) == 0 with input as {"jobs": {"build": {"steps": [{"run": "make"}]}}}
}

test_violation_reusable_workflow_call if {
	violations := unpinned_actions.violations with input as {"jobs": {"call": {"uses": "some-org/repo/.github/workflows/ci.yml@v1"}}}
	count(violations) == 1
	some v in violations
	v.discriminator == "call:job-uses"
}

test_no_violation_reusable_workflow_call_pinned if {
	count(unpinned_actions.violations) == 0 with input as {"jobs": {"call": {"uses": "some-org/repo/.github/workflows/ci.yml@a81bbbf8298c0fa03ea29cdc473d45769f953675"}}}
}

test_each_step_reported_separately if {
	violations := unpinned_actions.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "a/b@v1"},
		{"uses": "c/d@v2"},
	]}}}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
