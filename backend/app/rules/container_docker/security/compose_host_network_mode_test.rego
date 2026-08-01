package greensecops.container_docker.security.compose_host_network_mode_test

import data.greensecops.container_docker.security.compose_host_network_mode
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_for_host_network_mode if {
	violations := compose_host_network_mode.violations with input as _compose({"api": _service({"network_mode": "host"})})
	count(violations) == 1
}

test_no_violation_for_bridge_network_mode if {
	violations := compose_host_network_mode.violations with input as _compose({"api": _service({"network_mode": "bridge"})})
	count(violations) == 0
}

test_no_violation_when_network_mode_absent if {
	violations := compose_host_network_mode.violations with input as _compose({"api": _service({})})
	count(violations) == 0
}
