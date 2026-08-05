# METADATA
# title: Override makes a read-only root filesystem writable
# description: A Compose override sets read_only to false for a service the base file runs with a read-only root filesystem. A read-only root is one of the few container settings that turns a whole class of attack into an error message — a process that cannot write cannot drop a binary, persist a backdoor or modify the application it is running. Turning it off in the override means that protection is absent everywhere the override applies, while the base file keeps saying it is on.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       # compose.override.yml
#       services:
#         api:
#           read_only: false
#     good: |
#       # compose.override.yml — keep the read-only root, add a writable tmpfs
#       services:
#         api:
#           tmpfs:
#             - /tmp
#     fix: |
#       Leave read_only alone and mount a tmpfs or a named volume at whichever paths the process genuinely writes to. That is nearly always /tmp and a cache directory, both of which are better as tmpfs anyway since their contents should not survive a restart.
package greensecops.container_docker.security.compose_override_disables_read_only

import rego.v1

_base_is_read_only(name) if {
	some cf in input.compose_files
	not cf.is_override
	service := cf.services[name]
	is_object(service)
	service.read_only == true
}

violations contains violation if {
	some cf in input.compose_files
	cf.is_override

	some name, service in cf.services
	is_object(service)
	service.read_only == false
	_base_is_read_only(name)

	violation := {
		"rule": "compose_override_disables_read_only",
		"severity": "medium",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Override makes '%v' writable at the root, undoing the read-only filesystem the base file sets.", [name]),
		"discriminator": name,
	}
}
