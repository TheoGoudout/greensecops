package greensecops.container_runtime.reliability.container_restart_loop_test

import data.greensecops.container_runtime.reliability.container_restart_loop
import rego.v1

# Mirrors the ContainerStats objects the Action's post step ships
# (action/src/types.ts): `restart_count` is null for a container that was gone
# by the time `docker inspect` ran, which is not the same as zero restarts.

_containers(containers) := {"containers": containers}

test_violation_at_the_restart_threshold if {
	violations := container_restart_loop.violations with input as _containers([{"name": "api", "restart_count": 3}])
	count(violations) == 1
	some v in violations
	v.severity == "high"
}

test_violation_well_above_the_threshold if {
	violations := container_restart_loop.violations with input as _containers([{"name": "api", "restart_count": 12}])
	count(violations) == 1
}

test_no_violation_just_below_the_threshold if {
	violations := container_restart_loop.violations with input as _containers([{"name": "api", "restart_count": 2}])
	count(violations) == 0
}

test_no_violation_when_never_restarted if {
	violations := container_restart_loop.violations with input as _containers([{"name": "api", "restart_count": 0}])
	count(violations) == 0
}

# Null means "could not be read", which must not be treated as a huge number
# (or as zero) — there is simply no finding to make.
test_no_violation_when_restart_count_is_null if {
	violations := container_restart_loop.violations with input as _containers([{"name": "api", "restart_count": null}])
	count(violations) == 0
}

test_no_violation_when_restart_count_is_absent if {
	violations := container_restart_loop.violations with input as _containers([{"name": "api"}])
	count(violations) == 0
}

test_each_restarting_container_is_its_own_finding if {
	violations := container_restart_loop.violations with input as _containers([
		{"name": "api", "restart_count": 4},
		{"name": "worker", "restart_count": 9},
		{"name": "db", "restart_count": 0},
	])
	count(violations) == 2
}

test_evidence_names_the_container_and_the_count if {
	violations := container_restart_loop.violations with input as _containers([{"name": "api", "restart_count": 7}])
	some v in violations
	contains(v.evidence, "api")
	contains(v.evidence, "7")
}
