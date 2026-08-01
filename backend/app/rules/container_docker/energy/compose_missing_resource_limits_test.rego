package greensecops.container_docker.energy.compose_missing_resource_limits_test

import data.greensecops.container_docker.energy.compose_missing_resource_limits
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_no_limits_declared if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({})})
	count(violations) == 1
}

test_no_violation_with_deploy_resource_limits if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({"deploy": {"resources": {"limits": {"memory": "512M"}}}})})
	count(violations) == 0
}

test_no_violation_with_mem_limit_shorthand if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({"mem_limit": "512m"})})
	count(violations) == 0
}

test_no_violation_with_cpus_shorthand if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({"cpus": 1.5})})
	count(violations) == 0
}

# A service with neither image nor build runs nothing to limit.
test_no_violation_for_a_non_runnable_service if {
	violations := compose_missing_resource_limits.violations with input as _compose({"base": {"__start_line__": 2, "__end_line__": 3}})
	count(violations) == 0
}

test_violation_for_a_build_only_service if {
	violations := compose_missing_resource_limits.violations with input as _compose({"api": {
		"build": {"context": "."},
		"__start_line__": 2,
		"__end_line__": 5,
	}})
	count(violations) == 1
}

# An override fragment restates only what it changes; the base file may well
# declare limits, so absence here is not evidence of anything.
test_no_violation_on_a_compose_override_fragment if {
	violations := compose_missing_resource_limits.violations with input as {"compose_files": [{
		"__docker_file": "compose.override.yml",
		"is_override": true,
		"services": {"worker": _service({})},
	}]}
	count(violations) == 0
}
