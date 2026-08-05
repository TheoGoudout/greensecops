# METADATA
# title: Service does not run with a read-only root filesystem
# description: A Compose service does not set read_only, so its root filesystem is writable. A read-only root turns a whole class of attack into an error message — a process that cannot write cannot drop a binary, persist across a restart, or modify the application it is running — and most services never write outside /tmp anyway, which is better as a tmpfs regardless. It is judged on the merged configuration, so a setting an override supplies counts, and the finding is only raised when nothing in the running configuration sets it.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         api:
#           image: api:1.0
#     good: |
#       services:
#         api:
#           image: api:1.0
#           read_only: true
#           tmpfs:
#             - /tmp
#     fix: |
#       Set read_only and mount a tmpfs wherever the process genuinely writes. Start it in a non-production environment first — what breaks tells you exactly which paths the application writes to, which is usually a shorter list than anyone expects.
package greensecops.container_docker.security.compose_missing_read_only_filesystem

import rego.v1

_is_runnable(service) if service.image

_is_runnable(service) if service.build

# A privileged container makes the flag beside the point, and
# compose_privileged_container reports the larger problem that supersedes it.
_is_privileged(service) if service.privileged == true

# `effective_compose_files` is one document per configuration, with a base and
# its override already merged — absence is only meaningful about a complete
# configuration. The per-service `__docker_file` is preferred over the
# document's because a service the override introduces is not in the base file
# the merged document is named for.
violations contains violation if {
	some cf in input.effective_compose_files

	some name, service in cf.services
	is_object(service)
	_is_runnable(service)
	not _is_privileged(service)
	not service.read_only == true

	violation := {
		"rule": "compose_missing_read_only_filesystem",
		"severity": "low",
		"category": "security",
		"file_path": object.get(service, "__docker_file", object.get(cf, "__docker_file", "")),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' has a writable root filesystem, so a process inside it can drop a binary and persist. Set read_only with a tmpfs for the paths it writes.", [name]),
		"discriminator": name,
	}
}
