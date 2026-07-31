# METADATA
# title: Compose service runs privileged
# description: A service sets privileged true, which disables almost every container isolation boundary — the container gets all capabilities, unrestricted device access, and an unconfined seccomp/AppArmor profile. Escaping to the host from a privileged container is trivial.
# custom:
#   severity: critical
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         agent:
#           image: ghcr.io/example/agent:1.4.0
#           privileged: true
#     good: |
#       services:
#         agent:
#           image: ghcr.io/example/agent:1.4.0
#           cap_add:
#             - NET_ADMIN
#     fix: |
#       Remove privileged and grant only the specific capabilities the workload needs via cap_add, plus explicit device mappings for any hardware it must reach. If it genuinely needs full host access, run it outside the container runtime rather than pretending the boundary exists.
package greensecops.container_docker.security.compose_privileged_container

import rego.v1

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)
	service.privileged == true
	violation := {
		"rule": "compose_privileged_container",
		"severity": "critical",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' runs privileged, which removes container isolation from the host.", [name]),
		"discriminator": name,
	}
}
