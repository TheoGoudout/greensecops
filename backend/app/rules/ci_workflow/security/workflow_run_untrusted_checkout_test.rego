package greensecops.ci_workflow.security.workflow_run_untrusted_checkout_test

import data.greensecops.ci_workflow.security.workflow_run_untrusted_checkout as workflow_run_checkout
import rego.v1

_wf(on, steps) := {"on": on, "jobs": {"comment": {"runs-on": "ubuntu-latest", "steps": steps}}}

_workflow_run := {"workflow_run": {"workflows": ["CI"], "types": ["completed"]}}

test_violation_when_checking_out_the_triggering_head_sha if {
	violations := workflow_run_checkout.violations with input as _wf(_workflow_run, [{
		"uses": "actions/checkout@v5",
		"with": {"ref": "${{ github.event.workflow_run.head_sha }}"},
	}])
	count(violations) == 1
	some v in violations
	v.job == "comment"
	v.step_index == 0
}

test_violation_for_the_head_branch_ref if {
	violations := workflow_run_checkout.violations with input as _wf(_workflow_run, [{
		"uses": "actions/checkout@v5",
		"with": {"ref": "${{ github.event.workflow_run.head_branch }}"},
	}])
	count(violations) == 1
}

test_violation_for_the_list_trigger_form if {
	violations := workflow_run_checkout.violations with input as _wf(["workflow_run"], [{
		"uses": "actions/checkout@v5",
		"with": {"ref": "${{ github.event.workflow_run.head_sha }}"},
	}])
	count(violations) == 1
}

# The safe shape: check out the default branch, bring the other run's output
# across as an artifact.
test_no_violation_for_a_default_branch_checkout if {
	violations := workflow_run_checkout.violations with input as _wf(_workflow_run, [
		{"uses": "actions/checkout@v5"},
		{"uses": "actions/download-artifact@v5", "with": {"run-id": "${{ github.event.workflow_run.id }}"}},
	])
	count(violations) == 0
}

# Referencing the run id is data, not a checkout of its code.
test_no_violation_when_only_the_run_id_is_referenced if {
	violations := workflow_run_checkout.violations with input as _wf(_workflow_run, [{
		"uses": "actions/checkout@v5",
		"with": {"ref": "main"},
	}])
	count(violations) == 0
}

# The same checkout in a push workflow is checking out the repo's own code.
test_no_violation_without_a_workflow_run_trigger if {
	violations := workflow_run_checkout.violations with input as _wf({"push": {"branches": ["main"]}}, [{
		"uses": "actions/checkout@v5",
		"with": {"ref": "${{ github.event.workflow_run.head_sha }}"},
	}])
	count(violations) == 0
}

test_no_violation_when_the_step_has_no_with_block if {
	violations := workflow_run_checkout.violations with input as _wf(_workflow_run, [{"uses": "actions/checkout@v5"}])
	count(violations) == 0
}

test_each_offending_checkout_is_its_own_finding if {
	violations := workflow_run_checkout.violations with input as {
		"on": _workflow_run,
		"jobs": {
			"a": {"steps": [{"uses": "actions/checkout@v5", "with": {"ref": "${{ github.event.workflow_run.head_sha }}"}}]},
			"b": {"steps": [{"uses": "actions/checkout@v5", "with": {"ref": "${{ github.event.workflow_run.head_sha }}"}}]},
		},
	}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
