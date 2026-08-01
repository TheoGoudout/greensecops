package greensecops.container_runtime.reliability.container_oom_killed_test

import data.greensecops.container_runtime.reliability.container_oom_killed
import rego.v1

test_violation_when_a_container_was_oom_killed if {
	violations := container_oom_killed.violations with input as {"containers": [{"name": "worker", "oom_killed": true}]}
	count(violations) == 1
}

test_no_violation_when_no_container_was_killed if {
	violations := container_oom_killed.violations with input as {"containers": [{"name": "worker", "oom_killed": false}]}
	count(violations) == 0
}

test_each_killed_container_is_its_own_finding if {
	violations := container_oom_killed.violations with input as {"containers": [
		{"name": "a", "oom_killed": true},
		{"name": "b", "oom_killed": true},
	]}
	count(violations) == 2
}
