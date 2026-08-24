package greensecops.container_docker.energy.compose_service_unbounded_test

import data.greensecops.container_docker.energy.compose_service_unbounded as unbounded
import rego.v1

_compose(services) := {"effective_compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_svc(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

_rotated := {"logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}}

test_violation_when_neither_is_bounded if {
	violations := unbounded.violations with input as _compose({"worker": _svc({})})
	count(violations) == 1
	some v in violations
	contains(v.message, "memory or CPU limit")
	contains(v.message, "log rotation")
}

test_lists_only_the_missing_half if {
	violations := unbounded.violations with input as _compose({"worker": _svc(_rotated)})
	count(violations) == 1
	some v in violations
	v.context == "a memory or CPU limit"
}

test_no_violation_when_both_are_bounded if {
	violations := unbounded.violations with input as _compose({"worker": _svc(object.union(_rotated, {"mem_limit": "512m"}))})
	count(violations) == 0
}

test_deploy_resources_limits_count_as_a_limit if {
	violations := unbounded.violations with input as _compose({"worker": _svc(object.union(_rotated, {
		"deploy": {"resources": {"limits": {"memory": "512M"}}},
	}))})
	count(violations) == 0
}

# Naming another driver delegates retention, which is an answer.
test_a_non_default_log_driver_is_a_bound if {
	violations := unbounded.violations with input as _compose({"worker": _svc({
		"mem_limit": "512m",
		"logging": {"driver": "journald"},
	})})
	count(violations) == 0
}

test_no_violation_for_a_service_that_runs_nothing if {
	violations := unbounded.violations with input as {"effective_compose_files": [{
		"__docker_file": "compose.yml",
		"services": {"base": {"environment": {"X": "1"}}},
	}]}
	count(violations) == 0
}

test_one_finding_per_service if {
	violations := unbounded.violations with input as _compose({
		"api": _svc({}),
		"worker": _svc({}),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
