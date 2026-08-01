package greensecops.container_docker.security.compose_cap_add_sys_admin_test

import data.greensecops.container_docker.security.compose_cap_add_sys_admin
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_for_sys_admin if {
	violations := compose_cap_add_sys_admin.violations with input as _compose({"fuse": _service({"cap_add": ["SYS_ADMIN"]})})
	count(violations) == 1
}

test_violation_for_all if {
	violations := compose_cap_add_sys_admin.violations with input as _compose({"fuse": _service({"cap_add": ["ALL"]})})
	count(violations) == 1
}

test_violation_is_case_insensitive if {
	violations := compose_cap_add_sys_admin.violations with input as _compose({"fuse": _service({"cap_add": ["cap_sys_admin"]})})
	count(violations) == 1
}

test_no_violation_for_narrow_capability if {
	violations := compose_cap_add_sys_admin.violations with input as _compose({"net": _service({"cap_add": ["NET_ADMIN"]})})
	count(violations) == 0
}

test_no_violation_when_cap_add_absent if {
	violations := compose_cap_add_sys_admin.violations with input as _compose({"net": _service({})})
	count(violations) == 0
}
