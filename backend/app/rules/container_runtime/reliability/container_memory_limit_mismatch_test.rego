package greensecops.container_runtime.reliability.container_memory_limit_mismatch_test

import data.greensecops.container_runtime.reliability.container_memory_limit_mismatch
import rego.v1

test_violation_when_the_limit_is_far_above_peak if {
	violations := container_memory_limit_mismatch.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": 90000000,
		"mem_limit_bytes": 4294967296,
	}]}
	count(violations) == 1
}

test_no_violation_when_the_limit_is_proportionate if {
	violations := container_memory_limit_mismatch.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": 380000000,
		"mem_limit_bytes": 536870912,
	}]}
	count(violations) == 0
}

# A tiny sidecar under a modest limit is not over-provisioned in any way worth
# reporting, however large the ratio.
test_no_violation_for_a_tiny_workload if {
	violations := container_memory_limit_mismatch.violations with input as {"containers": [{
		"name": "sidecar",
		"peak_rss_bytes": 4000000,
		"mem_limit_bytes": 268435456,
	}]}
	count(violations) == 0
}
