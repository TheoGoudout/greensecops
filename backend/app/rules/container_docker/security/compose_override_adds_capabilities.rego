# METADATA
# title: Override grants a capability the base file dropped
# description: A Compose override adds a dangerous Linux capability to a service whose base definition drops all of them. Unlike most Compose fields, cap_add is *appended* across the merge rather than replaced — so the base's cap_drop and the override's cap_add both apply, and the specific capability named wins. That asymmetry is what makes this worth a rule of its own, because reading either file alone gives the wrong answer. SYS_ADMIN in particular is close to root, and NET_ADMIN, SYS_PTRACE and SYS_MODULE each provide a documented path out of the container.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       # compose.override.yml
#       services:
#         api:
#           cap_add:
#             - SYS_ADMIN
#     good: |
#       # compose.override.yml — grant only the specific capability needed
#       services:
#         api:
#           cap_add:
#             - NET_BIND_SERVICE
#     fix: |
#       Work out which operation actually failed and grant the narrowest capability that permits it — SYS_ADMIN is almost never the right answer, it is the one that makes the error go away. Where a debugger needs SYS_PTRACE, put it in a separate profile rather than in the override every developer loads.
package greensecops.container_docker.security.compose_override_adds_capabilities

import rego.v1

# Capabilities with a documented path to host compromise or to defeating the
# container boundary. NET_BIND_SERVICE and CHOWN are deliberately absent.
#
# SYS_ADMIN and ALL are absent too, and for a different reason:
# compose_cap_add_sys_admin already reports both at this severity wherever they
# appear. Repeating them here would put two findings on one line, which is
# noise however true each one is.
_dangerous_capabilities := {
	"SYS_MODULE",
	"SYS_PTRACE",
	"SYS_BOOT",
	"NET_ADMIN",
	"NET_RAW",
	"DAC_READ_SEARCH",
}

_base_drops_all(name) if {
	some cf in input.compose_files
	not cf.is_override
	service := cf.services[name]
	is_object(service)
	some dropped in service.cap_drop
	upper(sprintf("%v", [dropped])) == "ALL"
}

violations contains violation if {
	some cf in input.compose_files
	cf.is_override

	some name, service in cf.services
	is_object(service)

	some added in service.cap_add
	capability := upper(sprintf("%v", [added]))
	capability in _dangerous_capabilities

	# cap_add is appended across the merge, not replaced, so the base's
	# cap_drop: [ALL] does not cancel this — the named capability is granted.
	_base_drops_all(name)

	violation := {
		"rule": "compose_override_adds_capabilities",
		"severity": "high",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Override grants '%v' the %v capability, which survives the base file's cap_drop because Compose appends cap_add rather than replacing it.", [name, capability]),
		"discriminator": sprintf("%v-%v", [name, capability]),
	}
}
