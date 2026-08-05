package greensecops.cloud_aws.performance.lambda_tracing_disabled_test

import data.greensecops.cloud_aws.performance.lambda_tracing_disabled as no_tracing
import rego.v1

_fn(tracing_enabled) := {"lambda_functions": [{
	"name": "checkout",
	"region": "eu-west-1",
	"runtime": "python3.12",
	"environment_names": [],
	"vpc_configured": true,
	"tracing_enabled": tracing_enabled,
}]}

test_violation_when_tracing_is_off if {
	violations := no_tracing.violations with input as _fn(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "checkout"
	v.category == "performance"
	v.severity == "low"
}

test_no_violation_when_tracing_is_active if {
	violations := no_tracing.violations with input as _fn(true)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := no_tracing.violations with input as {"lambda_functions": []}
	count(violations) == 0
}

test_each_function_is_its_own_finding if {
	violations := no_tracing.violations with input as {"lambda_functions": [
		{"name": "checkout", "region": "eu-west-1", "tracing_enabled": false},
		{"name": "webhook", "region": "eu-west-1", "tracing_enabled": false},
		{"name": "cron", "region": "eu-west-1", "tracing_enabled": true},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
