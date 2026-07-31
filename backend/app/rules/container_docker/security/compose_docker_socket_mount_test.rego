package greensecops.container_docker.security.compose_docker_socket_mount_test

import data.greensecops.container_docker.security.compose_docker_socket_mount
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_for_short_syntax_mount if {
	violations := compose_docker_socket_mount.violations with input as _compose({"ci": _service({"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]})})
	count(violations) == 1
}

test_violation_for_read_only_mount if {
	violations := compose_docker_socket_mount.violations with input as _compose({"ci": _service({"volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"]})})
	count(violations) == 1
}

test_violation_for_long_syntax_mount if {
	violations := compose_docker_socket_mount.violations with input as _compose({"ci": _service({"volumes": [{
		"type": "bind",
		"source": "/var/run/docker.sock",
		"target": "/var/run/docker.sock",
	}]})})
	count(violations) == 1
}

test_no_violation_for_ordinary_volume if {
	violations := compose_docker_socket_mount.violations with input as _compose({"ci": _service({"volumes": ["./data:/data"]})})
	count(violations) == 0
}

test_no_violation_when_no_volumes if {
	violations := compose_docker_socket_mount.violations with input as _compose({"ci": _service({})})
	count(violations) == 0
}
