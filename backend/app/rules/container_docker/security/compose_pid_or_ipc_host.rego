# METADATA
# title: Service shares the host PID or IPC namespace
# description: A Compose service sets pid or ipc to host, removing the namespace isolation that separates the container from the machine. With the host PID namespace the container sees and can signal every process on the host, and /proc exposes their command lines and environment — which is where other containers' secrets live. The host IPC namespace shares shared-memory segments the same way. Together with compose_host_network_mode these are the isolation boundaries a container has left once it is not privileged.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         profiler:
#           image: profiler:1.0
#           pid: host
#     good: |
#       services:
#         profiler:
#           image: profiler:1.0
#           cap_add: [SYS_PTRACE]
#     fix: |
#       Drop the setting. A profiler or debugger that needs to see host processes usually needs SYS_PTRACE rather than the host PID namespace, and a service using shared memory should declare shm_size instead of joining the host's IPC namespace.
package greensecops.container_docker.security.compose_pid_or_ipc_host

import rego.v1

_namespace_keys := {"pid", "ipc"}

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)

	some key in _namespace_keys
	value := service[key]
	is_string(value)

	# `ipc: host` and `ipc: shareable` differ; only host leaves the container.
	lower(value) == "host"

	violation := {
		"rule": "compose_pid_or_ipc_host",
		"severity": "high",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' sets %v to host, so it shares the host's %v namespace and loses that isolation boundary.", [name, key, key]),
		"context": sprintf("%v: %v", [key, value]),
		"discriminator": sprintf("%v:%v", [name, key]),
	}
}
