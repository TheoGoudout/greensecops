package greensecops.energy.parallel_opportunity_test

import data.greensecops.energy.parallel_opportunity
import rego.v1

test_violation_three_independent_jobs if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"lint": {"steps": [{"run": "eslint ."}]},
		"test": {"steps": [{"run": "pytest"}]},
		"build": {"steps": [{"run": "make build"}]},
	}}
	count(violations) == 1
	some v in violations
	v.rule == "parallel_opportunity"
}

test_no_violation_jobs_with_needs if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"build": {"steps": [{"run": "make build"}]},
		"test": {
			"needs": ["build"],
			"steps": [{"run": "pytest"}],
		},
		"deploy": {
			"needs": ["test"],
			"steps": [{"run": "make deploy"}],
		},
	}}
	count(violations) == 0
}

test_no_violation_only_two_independent_jobs if {
	violations := parallel_opportunity.violations with input as {"jobs": {
		"lint": {"steps": [{"run": "eslint ."}]},
		"test": {"steps": [{"run": "pytest"}]},
	}}
	count(violations) == 0
}
