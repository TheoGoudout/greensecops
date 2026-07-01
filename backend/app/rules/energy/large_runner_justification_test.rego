package greensecops.energy.large_runner_justification_test

import data.greensecops.energy.large_runner_justification
import rego.v1

test_violation_gpu_runner_no_heavy_workload if {
	violations := large_runner_justification.violations with input as {
		"jobs": {
			"ci": {
				"runs-on": "ubuntu-gpu",
				"steps": [
					{"uses": "actions/checkout@v4"},
					{"run": "echo hello"},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "large_runner_justification"
}

test_no_violation_large_runner_with_build_step if {
	violations := large_runner_justification.violations with input as {
		"jobs": {
			"compile": {
				"runs-on": "ubuntu-latest-large",
				"steps": [
					{"uses": "actions/checkout@v4"},
					{"run": "cargo build --release"},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_standard_runner if {
	violations := large_runner_justification.violations with input as {
		"jobs": {
			"test": {
				"runs-on": "ubuntu-latest",
				"steps": [{"run": "echo hi"}],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_gpu_runner_with_train_step if {
	violations := large_runner_justification.violations with input as {
		"jobs": {
			"ml": {
				"runs-on": "ubuntu-gpu-large",
				"steps": [{"run": "python train.py --epochs 10"}],
			},
		},
	}
	count(violations) == 0
}
