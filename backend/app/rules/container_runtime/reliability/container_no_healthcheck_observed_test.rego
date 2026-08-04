package greensecops.container_runtime.reliability.container_no_healthcheck_observed_test

import data.greensecops.container_runtime.reliability.container_no_healthcheck_observed as no_healthcheck
import rego.v1

# `observed` is false for a container that lived entirely between two daemon
# ticks (action/src/types.ts). Its `has_healthcheck` is then a default rather
# than a reading, so it must not produce a finding.

_containers(containers) := {"containers": containers}

test_violation_when_an_observed_container_has_no_healthcheck if {
	violations := no_healthcheck.violations with input as _containers([{
		"name": "api",
		"has_healthcheck": false,
		"observed": true,
	}])
	count(violations) == 1
	some v in violations
	contains(v.evidence, "api")
}

test_no_violation_when_a_healthcheck_is_configured if {
	violations := no_healthcheck.violations with input as _containers([{
		"name": "api",
		"has_healthcheck": true,
		"observed": true,
	}])
	count(violations) == 0
}

test_no_violation_for_an_unobserved_container if {
	violations := no_healthcheck.violations with input as _containers([{
		"name": "api",
		"has_healthcheck": false,
		"observed": false,
	}])
	count(violations) == 0
}

test_no_violation_when_observed_is_absent if {
	violations := no_healthcheck.violations with input as _containers([{"name": "api", "has_healthcheck": false}])
	count(violations) == 0
}

# This rule and healthcheck_never_healthy are complementary, never both true:
# one needs has_healthcheck false, the other needs it true.
test_does_not_overlap_with_healthcheck_never_healthy if {
	violations := no_healthcheck.violations with input as _containers([{
		"name": "api",
		"has_healthcheck": true,
		"health_status": "unhealthy",
		"observed": true,
	}])
	count(violations) == 0
}

test_each_unhealthchecked_container_is_its_own_finding if {
	violations := no_healthcheck.violations with input as _containers([
		{"name": "a", "has_healthcheck": false, "observed": true},
		{"name": "b", "has_healthcheck": false, "observed": true},
	])
	count(violations) == 2
}
