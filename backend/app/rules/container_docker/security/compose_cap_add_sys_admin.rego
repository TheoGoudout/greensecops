# METADATA
# title: Service grants SYS_ADMIN or ALL capabilities
# description: A service adds CAP_SYS_ADMIN or ALL. SYS_ADMIN is the broadest capability in Linux — it covers mount, pivot_root and cgroup manipulation, and is the usual route out of a container — so granting it is close to running privileged while looking narrower.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         fuse:
#           image: ghcr.io/example/fuse:0.9.1
#           cap_add:
#             - SYS_ADMIN
#     good: |
#       services:
#         fuse:
#           image: ghcr.io/example/fuse:0.9.1
#           devices:
#             - /dev/fuse
#           cap_add:
#             - SYS_ADMIN
#           security_opt:
#             - apparmor=docker-fuse
#     fix: |
#       Grant the narrowest capability that works — most workloads asking for SYS_ADMIN actually need a single device mapping or one of NET_ADMIN, SYS_PTRACE or MKNOD. Where SYS_ADMIN is unavoidable (FUSE mounts are the common case), pair it with a restrictive AppArmor or seccomp profile and record why.
package greensecops.container_docker.security.compose_cap_add_sys_admin

import rego.v1

_dangerous := {"sys_admin", "cap_sys_admin", "all"}

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)
	some capability in service.cap_add
	is_string(capability)
	lower(capability) in _dangerous
	violation := {
		"rule": "compose_cap_add_sys_admin",
		"severity": "high",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' grants capability %v, which is close to full privilege. Grant only the specific capability the workload needs.", [name, capability]),
		"context": capability,
		"discriminator": sprintf("%v:%v", [name, lower(capability)]),
	}
}
