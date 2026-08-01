package greensecops.container_runtime.energy.container_unbounded_memory_test

import data.greensecops.container_runtime.energy.container_unbounded_memory
import rego.v1

test_violation_when_a_real_workload_has_no_limit if {
	violations := container_unbounded_memory.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": 420000000,
		"mem_limit_bytes": 0,
	}]}
	count(violations) == 1
}

test_no_violation_when_a_limit_is_set if {
	violations := container_unbounded_memory.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": 420000000,
		"mem_limit_bytes": 805306368,
	}]}
	count(violations) == 0
}

# A limit on a container that barely uses memory is ceremony, not a fix.
test_no_violation_for_a_trivial_workload if {
	violations := container_unbounded_memory.violations with input as {"containers": [{
		"name": "sidecar",
		"peak_rss_bytes": 4000000,
		"mem_limit_bytes": 0,
	}]}
	count(violations) == 0
}

# Null is what the collector reports for a container that was already gone by
# the post step. Reading it as "declared no limit" would invent this finding
# for every container the job cleaned up after itself.
test_no_violation_when_the_limit_could_not_be_read if {
	violations := container_unbounded_memory.violations with input as {"containers": [{
		"name": "worker",
		"peak_rss_bytes": 420000000,
		"mem_limit_bytes": null,
	}]}
	count(violations) == 0
}

test_no_violation_when_nothing_was_measured if {
	violations := container_unbounded_memory.violations with input as {"containers": [{
		"name": "worker",
		"peak_rss_bytes": null,
		"mem_limit_bytes": 0,
	}]}
	count(violations) == 0
}
