package greensecops.container_docker.security.compose_privileged_container_test

import data.greensecops.container_docker.security.compose_privileged_container
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_privileged_is_true if {
	violations := compose_privileged_container.violations with input as _compose({"agent": _service({"privileged": true})})
	count(violations) == 1
	some v in violations
	v.service_name == "agent"
	v.line_start == 2
}

test_no_violation_when_privileged_is_false if {
	violations := compose_privileged_container.violations with input as _compose({"agent": _service({"privileged": false})})
	count(violations) == 0
}

test_no_violation_when_privileged_is_absent if {
	violations := compose_privileged_container.violations with input as _compose({"agent": _service({})})
	count(violations) == 0
}

# A service key with an empty body parses to null and must not crash the rule.
test_no_violation_for_null_service if {
	violations := compose_privileged_container.violations with input as _compose({"agent": null})
	count(violations) == 0
}

test_each_privileged_service_is_its_own_finding if {
	violations := compose_privileged_container.violations with input as _compose({
		"a": _service({"privileged": true}),
		"b": _service({"privileged": true}),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
