package greensecops.ci_workflow.performance.matrix_max_parallel_one_test

import data.greensecops.ci_workflow.performance.matrix_max_parallel_one as max_parallel_one
import rego.v1

_MATRIX := {"python": ["3.11", "3.12", "3.13"]}

_job(strategy) := {"jobs": {"test": {"runs-on": "ubuntu-latest", "strategy": strategy, "steps": [{"run": "pytest"}]}}}

test_violation_when_max_parallel_is_one if {
	violations := max_parallel_one.violations with input as _job({"max-parallel": 1, "matrix": _MATRIX})
	count(violations) == 1
	some v in violations
	v.job == "test"
}

test_no_violation_without_max_parallel if {
	violations := max_parallel_one.violations with input as _job({"matrix": _MATRIX})
	count(violations) == 0
}

# A cap above one still runs legs concurrently, which is a throttle rather than
# a serialisation.
test_no_violation_for_a_higher_cap if {
	violations := max_parallel_one.violations with input as _job({"max-parallel": 2, "matrix": _MATRIX})
	count(violations) == 0
}

# max-parallel means nothing without a matrix to apply it to.
test_no_violation_without_a_matrix if {
	violations := max_parallel_one.violations with input as _job({"max-parallel": 1})
	count(violations) == 0
}

test_no_violation_when_no_strategy_is_declared if {
	violations := max_parallel_one.violations with input as {"jobs": {"test": {"steps": [{"run": "pytest"}]}}}
	count(violations) == 0
}

test_each_serialised_job_is_its_own_finding if {
	violations := max_parallel_one.violations with input as {"jobs": {
		"test": {"strategy": {"max-parallel": 1, "matrix": _MATRIX}, "steps": []},
		"lint": {"strategy": {"max-parallel": 1, "matrix": _MATRIX}, "steps": []},
		"build": {"strategy": {"matrix": _MATRIX}, "steps": []},
	}}
	count(violations) == 2
	{v.discriminator | some v in violations} == {"test", "lint"}
}
