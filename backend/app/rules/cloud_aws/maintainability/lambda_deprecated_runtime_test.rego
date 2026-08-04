package greensecops.cloud_aws.maintainability.lambda_deprecated_runtime_test

import data.greensecops.cloud_aws.maintainability.lambda_deprecated_runtime as deprecated_runtime
import rego.v1

_functions(functions) := {"lambda_functions": functions}

_fn(name, runtime) := {
	"name": name,
	"region": "eu-west-1",
	"runtime": runtime,
	"public_url": false,
}

test_violation_for_a_deprecated_python_runtime if {
	violations := deprecated_runtime.violations with input as _functions([_fn("api", "python3.8")])
	count(violations) == 1
	some v in violations
	v.resource_id == "api"
	v.region == "eu-west-1"
	contains(v.message, "python3.8")
}

test_violation_for_a_deprecated_node_runtime if {
	violations := deprecated_runtime.violations with input as _functions([_fn("api", "nodejs16.x")])
	count(violations) == 1
}

test_violation_for_go1_x if {
	violations := deprecated_runtime.violations with input as _functions([_fn("api", "go1.x")])
	count(violations) == 1
}

test_no_violation_for_a_current_python_runtime if {
	violations := deprecated_runtime.violations with input as _functions([_fn("api", "python3.13")])
	count(violations) == 0
}

test_no_violation_for_a_current_node_runtime if {
	violations := deprecated_runtime.violations with input as _functions([_fn("api", "nodejs22.x")])
	count(violations) == 0
}

# A custom runtime is maintained by its owner, not by AWS's schedule.
test_no_violation_for_a_custom_runtime if {
	violations := deprecated_runtime.violations with input as _functions([_fn("api", "provided.al2023")])
	count(violations) == 0
}

# The collector defaults an unreadable runtime to the empty string.
test_no_violation_for_an_unknown_runtime if {
	violations := deprecated_runtime.violations with input as _functions([_fn("api", "")])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := deprecated_runtime.violations with input as _functions([])
	count(violations) == 0
}

test_each_deprecated_function_is_its_own_finding if {
	violations := deprecated_runtime.violations with input as _functions([
		_fn("api", "python3.8"),
		_fn("worker", "nodejs14.x"),
		_fn("cron", "python3.13"),
	])
	count(violations) == 2
	{v.resource_id | some v in violations} == {"api", "worker"}
}
