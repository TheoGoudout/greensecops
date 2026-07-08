package greensecops.energy.caching_missing_test

import data.greensecops.energy.caching_missing
import rego.v1

test_violation_setup_without_cache_emits_step_index if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
		{"uses": "actions/setup-node@v4"},
		{"run": "npm install"},
	]}}}
	count(violations) == 1
	some v in violations
	v.step == "actions/setup-node@v4"
	v.step_index == 1
}

test_no_violation_cache_enabled if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/setup-node@v4", "with": {"cache": "npm"}},
		{"run": "npm install"},
	]}}}
	count(violations) == 0
}

test_violation_no_setup_step_is_job_level if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
		{"run": "pip install -r requirements.txt"},
	]}}}
	count(violations) == 1
	some v in violations
	not v.step_index
}
