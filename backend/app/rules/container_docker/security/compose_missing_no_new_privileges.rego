# METADATA
# title: Service does not set no-new-privileges
# description: A Compose service does not set the no-new-privileges security option. Without it a process inside the container can still gain privileges through a setuid binary, which is what turns a limited foothold into root in the container namespace — and most base images ship several setuid binaries (su, mount, ping) that nothing in a typical service uses. The flag is a single line, costs nothing at runtime, and closes the escalation path that dropping to a non-root USER otherwise leaves open.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         api:
#           image: api:1.0
#           user: "10001"
#     good: |
#       services:
#         api:
#           image: api:1.0
#           user: "10001"
#           security_opt:
#             - no-new-privileges:true
#     fix: |
#       Add `no-new-privileges:true` under security_opt. If something then breaks it is because the container was relying on a setuid binary, which is worth knowing — the usual fix is to grant the specific capability the process needs rather than to remove the flag.
package greensecops.container_docker.security.compose_missing_no_new_privileges

import rego.v1

_is_runnable(service) if service.image

_is_runnable(service) if service.build

_sets_no_new_privileges(service) if {
	some option in service.security_opt
	is_string(option)
	regex.match(`(?i)^no-new-privileges\s*[:=]\s*(true|1)$`, trim_space(option))
}

# A privileged container ignores the flag entirely, and
# compose_privileged_container already reports the far larger problem. Firing
# both would add a low-severity note to a critical finding that supersedes it.
_is_privileged(service) if service.privileged == true

violations contains violation if {
	some cf in input.compose_files

	# An override fragment inherits security_opt it does not restate.
	not cf.is_override

	some name, service in cf.services
	is_object(service)
	_is_runnable(service)
	not _is_privileged(service)
	not _sets_no_new_privileges(service)

	violation := {
		"rule": "compose_missing_no_new_privileges",
		"severity": "low",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' does not set no-new-privileges, so a setuid binary in the image can still be used to escalate. Add 'no-new-privileges:true' under security_opt.", [name]),
		"discriminator": name,
	}
}
