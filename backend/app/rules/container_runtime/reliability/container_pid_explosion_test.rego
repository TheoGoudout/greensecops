package greensecops.container_runtime.reliability.container_pid_explosion_test

import data.greensecops.container_runtime.reliability.container_pid_explosion
import rego.v1

_containers(containers) := {"containers": containers}

test_violation_above_the_threshold if {
	violations := container_pid_explosion.violations with input as _containers([{"name": "worker", "peak_pids": 4200}])
	count(violations) == 1
	some v in violations
	contains(v.evidence, "4200")
}

test_no_violation_at_the_threshold if {
	violations := container_pid_explosion.violations with input as _containers([{"name": "worker", "peak_pids": 1000}])
	count(violations) == 0
}

test_no_violation_for_a_normal_process_count if {
	violations := container_pid_explosion.violations with input as _containers([{"name": "worker", "peak_pids": 64}])
	count(violations) == 0
}

# Null means the container was never sampled, not that it ran zero processes.
test_no_violation_when_peak_pids_is_null if {
	violations := container_pid_explosion.violations with input as _containers([{"name": "worker", "peak_pids": null}])
	count(violations) == 0
}

test_no_violation_when_peak_pids_is_absent if {
	violations := container_pid_explosion.violations with input as _containers([{"name": "worker"}])
	count(violations) == 0
}

test_each_container_over_the_threshold_is_its_own_finding if {
	violations := container_pid_explosion.violations with input as _containers([
		{"name": "a", "peak_pids": 2000},
		{"name": "b", "peak_pids": 10},
		{"name": "c", "peak_pids": 5000},
	])
	count(violations) == 2
}
