package greensecops.container_runtime.reliability.container_nonzero_exit_test

import data.greensecops.container_runtime.reliability.container_nonzero_exit
import rego.v1

# `exit_code` is null for a container that was still running when the job
# ended (action/src/types.ts) — the normal state for a long-lived service, and
# emphatically not a failure.

_containers(containers) := {"containers": containers}

test_violation_on_a_failing_exit_code if {
	violations := container_nonzero_exit.violations with input as _containers([{"name": "migrate", "exit_code": 1}])
	count(violations) == 1
}

test_violation_on_a_signal_exit_code if {
	violations := container_nonzero_exit.violations with input as _containers([{"name": "api", "exit_code": 137}])
	count(violations) == 1
	some v in violations
	contains(v.evidence, "137")
}

test_no_violation_on_a_clean_exit if {
	violations := container_nonzero_exit.violations with input as _containers([{"name": "migrate", "exit_code": 0}])
	count(violations) == 0
}

test_no_violation_when_still_running if {
	violations := container_nonzero_exit.violations with input as _containers([{"name": "api", "exit_code": null}])
	count(violations) == 0
}

test_no_violation_when_exit_code_is_absent if {
	violations := container_nonzero_exit.violations with input as _containers([{"name": "api"}])
	count(violations) == 0
}

test_each_failing_container_is_its_own_finding if {
	violations := container_nonzero_exit.violations with input as _containers([
		{"name": "a", "exit_code": 2},
		{"name": "b", "exit_code": 0},
		{"name": "c", "exit_code": 9},
	])
	count(violations) == 2
}
