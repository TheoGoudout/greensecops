package greensecops.ci_workflow.energy.runner_sizing_test

import data.greensecops.ci_workflow.energy.runner_sizing
import rego.v1

_job(runs_on, steps) := {"jobs": {"check": {"runs-on": runs_on, "steps": steps}}}

_lint := [{"run": "yamllint ."}]

test_violation_large_github_runner if {
	count(runner_sizing.violations) == 1 with input as _job("ubuntu-latest-16-cores", _lint)
}

test_violation_xlarge_label if {
	count(runner_sizing.violations) == 1 with input as _job("ubuntu-22.04-2xlarge", _lint)
}

test_violation_gpu_runner if {
	count(runner_sizing.violations) == 1 with input as _job("gpu-a100", _lint)
}

# Neither old rule saw the list form, so a self-hosted GPU job was invisible.
test_violation_list_form_runs_on if {
	count(runner_sizing.violations) == 1 with input as _job(["self-hosted", "gpu"], _lint)
}

# Nor the runner-group mapping.
test_violation_group_form_runs_on if {
	count(runner_sizing.violations) == 1 with input as _job({"group": "big", "labels": ["xlarge"]}, _lint)
}

test_no_violation_default_runner if {
	count(runner_sizing.violations) == 0 with input as _job("ubuntu-latest", _lint)
}

test_no_violation_heavy_run_step if {
	count(runner_sizing.violations) == 0 with input as _job("ubuntu-latest-16-cores", [{"run": "cargo build --release"}])
}

test_no_violation_heavy_action if {
	count(runner_sizing.violations) == 0 with input as _job("ubuntu-latest-16-cores", [{"uses": "docker/build-push-action@v6"}])
}

test_no_violation_matrix_job if {
	input_doc := {"jobs": {"check": {
		"runs-on": "ubuntu-latest-16-cores",
		"strategy": {"matrix": {"os": ["a", "b"]}},
		"steps": _lint,
	}}}
	count(runner_sizing.violations) == 0 with input as input_doc
}

# `runner_sizing` used to fire on any large runner with three or fewer steps,
# which reported a two-step release build as oversized.
test_no_violation_short_but_heavy_job if {
	count(runner_sizing.violations) == 0 with input as _job("ubuntu-latest-16-cores", [
		{"uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"},
		{"run": "make release"},
	])
}

test_one_finding_per_job if {
	violations := runner_sizing.violations with input as {"jobs": {
		"a": {"runs-on": "gpu-a100", "steps": _lint},
		"b": {"runs-on": "gpu-a100", "steps": _lint},
	}}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
