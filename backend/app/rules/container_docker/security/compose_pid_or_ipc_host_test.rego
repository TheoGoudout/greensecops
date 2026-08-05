package greensecops.container_docker.security.compose_pid_or_ipc_host_test

import data.greensecops.container_docker.security.compose_pid_or_ipc_host as pid_or_ipc_host
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"is_override": false,
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_for_pid_host if {
	violations := pid_or_ipc_host.violations with input as _compose({"profiler": _service({"pid": "host"})})
	count(violations) == 1
	some v in violations
	v.service_name == "profiler"
	v.line_start == 2
}

test_violation_for_ipc_host if {
	violations := pid_or_ipc_host.violations with input as _compose({"renderer": _service({"ipc": "host"})})
	count(violations) == 1
}

test_violation_is_case_insensitive if {
	violations := pid_or_ipc_host.violations with input as _compose({"profiler": _service({"pid": "HOST"})})
	count(violations) == 1
}

# `ipc: shareable` shares a namespace between containers, not with the host.
test_no_violation_for_ipc_shareable if {
	violations := pid_or_ipc_host.violations with input as _compose({"renderer": _service({"ipc": "shareable"})})
	count(violations) == 0
}

# Joining another container's namespace is a different thing from joining the
# host's.
test_no_violation_for_a_container_namespace if {
	violations := pid_or_ipc_host.violations with input as _compose({"sidecar": _service({"pid": "container:app"})})
	count(violations) == 0
}

test_no_violation_when_neither_key_is_set if {
	violations := pid_or_ipc_host.violations with input as _compose({"app": _service({})})
	count(violations) == 0
}

# A service key with an empty body parses to null and must not crash the rule.
test_no_violation_for_a_null_service if {
	violations := pid_or_ipc_host.violations with input as _compose({"app": null})
	count(violations) == 0
}

# Presence-based rules fire in override fragments too — an override that adds
# `pid: host` is adding it to the merged config.
test_violation_in_an_override_fragment if {
	violations := pid_or_ipc_host.violations with input as {"compose_files": [{
		"__docker_file": "compose.override.yml",
		"is_override": true,
		"services": {"profiler": _service({"pid": "host"})},
	}]}
	count(violations) == 1
}

test_both_namespaces_on_one_service_are_separate_findings if {
	violations := pid_or_ipc_host.violations with input as _compose({"profiler": _service({"pid": "host", "ipc": "host"})})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
