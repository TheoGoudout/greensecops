package greensecops.ci_workflow.energy.parallel_opportunity_test

import data.greensecops.ci_workflow.energy.parallel_opportunity
import rego.v1

test_violation_sequential_needs_chain if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"lint": {"steps": [{"run": "eslint ."}]},
		"test": {"needs": "lint", "steps": [{"run": "pytest"}]},
		"build": {"needs": "test", "steps": [{"run": "make build"}]},
	}}
	count(violations) == 1
	some v in violations
	v.rule == "parallel_opportunity"
	v.job == null
}

test_violation_sequential_needs_chain_list_form if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"lint": {"steps": [{"run": "eslint ."}]},
		"test": {"needs": ["lint"], "steps": [{"run": "pytest"}]},
		"build": {"needs": ["test"], "steps": [{"run": "make build"}]},
	}}
	count(violations) == 1
}

test_no_violation_independent_jobs if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"lint": {"steps": [{"run": "eslint ."}]},
		"test": {"steps": [{"run": "pytest"}]},
		"build": {"steps": [{"run": "make build"}]},
	}}
	count(violations) == 0
}

test_no_violation_fan_in_single_dependency if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"build": {"steps": [{"run": "make build"}]},
		"test": {"needs": ["build"], "steps": [{"run": "pytest"}]},
		"e2e": {"needs": ["build"], "steps": [{"run": "make e2e"}]},
	}}
	count(violations) == 0
}

# ─── The false positives this rework exists to remove ─────────────────────────

# The premise of the message is "if these jobs do not consume each other's
# outputs" — which the old rule never checked, so it fired on every pipeline
# that did.
test_no_violation_when_the_chain_passes_outputs if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"prepare": {
			"outputs": {"tag": "${{ steps.t.outputs.tag }}"},
			"steps": [{"id": "t", "run": "echo tag=v1 >> $GITHUB_OUTPUT"}],
		},
		"build": {
			"needs": "prepare",
			"outputs": {"digest": "${{ steps.b.outputs.digest }}"},
			"steps": [{"id": "b", "run": "build ${{ needs.prepare.outputs.tag }}"}],
		},
		"deploy": {
			"needs": "build",
			"steps": [{"run": "deploy ${{ needs.build.outputs.digest }}"}],
		},
	}}
	count(violations) == 0
}

# Artifact hand-off is a real dependency too, even with no job outputs.
test_no_violation_when_the_chain_passes_artifacts if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"compile": {"steps": [{"uses": "actions/upload-artifact@v4"}]},
		"package": {"needs": "compile", "steps": [
			{"uses": "actions/download-artifact@v4"},
			{"uses": "actions/upload-artifact@v4"},
		]},
		"ship": {"needs": "package", "steps": [{"uses": "actions/download-artifact@v4"}]},
	}}
	count(violations) == 0
}

# ─── Shape ───────────────────────────────────────────────────────────────────

# A diamond used to produce a combinatorial number of identical findings, all of
# which collapsed onto one dedup key anyway.
test_one_finding_per_workflow_however_many_chains if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"a": {"steps": []},
		"b1": {"needs": "a", "steps": []},
		"b2": {"needs": "a", "steps": []},
		"c": {"needs": ["b1", "b2"], "steps": []},
		"d": {"needs": "c", "steps": []},
	}}
	count(violations) == 1
	some v in violations
	v.discriminator == "needs-chain"
}
