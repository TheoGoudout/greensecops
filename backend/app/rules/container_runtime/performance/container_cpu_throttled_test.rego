package greensecops.container_runtime.performance.container_cpu_throttled_test

import data.greensecops.container_runtime.performance.container_cpu_throttled
import rego.v1

test_violation_when_throttled_in_most_periods if {
	violations := container_cpu_throttled.violations with input as {"containers": [{
		"name": "api",
		"cpu_throttled_percent": 42.0,
	}]}
	count(violations) == 1
}

# Bursty workloads clip their quota occasionally; that is the quota working,
# not a finding.
test_no_violation_for_occasional_throttling if {
	violations := container_cpu_throttled.violations with input as {"containers": [{
		"name": "api",
		"cpu_throttled_percent": 2.0,
	}]}
	count(violations) == 0
}

# Null is the reading for a container with no CPU quota at all — there is
# nothing to throttle against, so there is nothing to report.
test_no_violation_when_no_quota_is_set if {
	violations := container_cpu_throttled.violations with input as {"containers": [{
		"name": "api",
		"cpu_throttled_percent": null,
	}]}
	count(violations) == 0
}
