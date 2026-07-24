package greensecops.ci_workflow.energy.parallel_opportunity_test

import data.greensecops.ci_workflow.energy.parallel_opportunity
import rego.v1

test_violation_sequential_needs_chain if {
	violations := parallel_opportunity.violations with input as {
		"jobs": {
			"lint": {"steps": [{"run": "eslint ."}]},
			"test": {
				"needs": "lint",
				"steps": [{"run": "pytest"}],
			},
			"build": {
				"needs": "test",
				"steps": [{"run": "make build"}],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "parallel_opportunity"
}

test_violation_sequential_needs_chain_list_form if {
	violations := parallel_opportunity.violations with input as {
		"jobs": {
			"lint": {"steps": [{"run": "eslint ."}]},
			"test": {
				"needs": ["lint"],
				"steps": [{"run": "pytest"}],
			},
			"build": {
				"needs": ["test"],
				"steps": [{"run": "make build"}],
			},
		},
	}
	count(violations) == 1
}

test_no_violation_independent_jobs if {
	violations := parallel_opportunity.violations with input as {
		"jobs": {
			"lint": {"steps": [{"run": "eslint ."}]},
			"test": {"steps": [{"run": "pytest"}]},
			"build": {"steps": [{"run": "make build"}]},
		},
	}
	count(violations) == 0
}

test_no_violation_fan_in_single_dependency if {
	# build; test and e2e both need build -> genuine parallelism (chain depth 1),
	# so this must NOT be flagged.
	violations := parallel_opportunity.violations with input as {
		"jobs": {
			"build": {"steps": [{"run": "make build"}]},
			"test": {
				"needs": ["build"],
				"steps": [{"run": "pytest"}],
			},
			"e2e": {
				"needs": ["build"],
				"steps": [{"run": "make e2e"}],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_single_dependency_two_jobs if {
	violations := parallel_opportunity.violations with input as {
		"jobs": {
			"build": {"steps": [{"run": "make build"}]},
			"deploy": {
				"needs": ["build"],
				"steps": [{"run": "make deploy"}],
			},
		},
	}
	count(violations) == 0
}
