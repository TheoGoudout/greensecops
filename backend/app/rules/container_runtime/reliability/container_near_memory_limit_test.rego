package greensecops.container_runtime.reliability.container_near_memory_limit_test

import data.greensecops.container_runtime.reliability.container_near_memory_limit
import rego.v1

test_violation_when_peak_is_within_the_margin if {
	violations := container_near_memory_limit.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": 258000000,
		"mem_limit_bytes": 268435456,
		"oom_killed": false,
	}]}
	count(violations) == 1
}

test_no_violation_with_comfortable_headroom if {
	violations := container_near_memory_limit.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": 190000000,
		"mem_limit_bytes": 536870912,
		"oom_killed": false,
	}]}
	count(violations) == 0
}

# container_oom_killed already reports this container, at a higher severity and
# with the same fix. Firing both would double-count one problem.
test_no_violation_when_already_oom_killed if {
	violations := container_near_memory_limit.violations with input as {"containers": [{
		"name": "worker",
		"peak_rss_bytes": 268000000,
		"mem_limit_bytes": 268435456,
		"oom_killed": true,
	}]}
	count(violations) == 0
}

test_no_violation_when_no_limit_is_declared if {
	violations := container_near_memory_limit.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": 258000000,
		"mem_limit_bytes": 0,
		"oom_killed": false,
	}]}
	count(violations) == 0
}

test_no_violation_when_the_container_was_never_sampled if {
	violations := container_near_memory_limit.violations with input as {"containers": [{
		"name": "api",
		"peak_rss_bytes": null,
		"mem_limit_bytes": 268435456,
		"oom_killed": false,
	}]}
	count(violations) == 0
}
