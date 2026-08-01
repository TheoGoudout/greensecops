package greensecops.container_runtime.reliability.healthcheck_never_healthy_test

import data.greensecops.container_runtime.reliability.healthcheck_never_healthy
import rego.v1

test_violation_when_the_container_stayed_unhealthy if {
	violations := healthcheck_never_healthy.violations with input as {"containers": [{
		"name": "api",
		"has_healthcheck": true,
		"health_status": "unhealthy",
	}]}
	count(violations) == 1
}

test_violation_when_it_never_left_starting if {
	violations := healthcheck_never_healthy.violations with input as {"containers": [{
		"name": "api",
		"has_healthcheck": true,
		"health_status": "starting",
	}]}
	count(violations) == 1
}

test_no_violation_when_healthy if {
	violations := healthcheck_never_healthy.violations with input as {"containers": [{
		"name": "api",
		"has_healthcheck": true,
		"health_status": "healthy",
	}]}
	count(violations) == 0
}

# Without a healthcheck this rule has nothing to say — the static
# missing_healthcheck rule covers that case instead.
test_no_violation_without_a_healthcheck if {
	violations := healthcheck_never_healthy.violations with input as {"containers": [{
		"name": "api",
		"has_healthcheck": false,
		"health_status": "none",
	}]}
	count(violations) == 0
}
