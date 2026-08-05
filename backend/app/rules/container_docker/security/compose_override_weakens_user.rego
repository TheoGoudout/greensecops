# METADATA
# title: Override runs a service as root that the base does not
# description: A Compose override sets a service back to root for a service the base file deliberately runs as an unprivileged user. This is the pattern where a hardening decision is made once and then quietly undone in the file nobody reviews — the base is what gets read in a code review, and the override is what actually runs locally and, often enough, in CI. The result is that every finding about the base's user configuration is true and irrelevant. Compose merges scalars by replacement, so the override's value is simply the one that applies.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       # compose.override.yml
#       services:
#         api:
#           user: root
#     good: |
#       # compose.override.yml — keeps the base's user, adds only what differs
#       services:
#         api:
#           volumes:
#             - ./src:/app/src
#     fix: |
#       Drop the user override. If it exists because a mounted host directory is owned by your uid, set the uid explicitly rather than reaching for root — `user: "1000:1000"` solves the ownership problem without giving the container the rest of root's authority.
package greensecops.container_docker.security.compose_override_weakens_user

import rego.v1

_root_user(value) if lower(trim_space(sprintf("%v", [value]))) in {"root", "0"}

_root_user(value) if startswith(sprintf("%v", [value]), "0:")

_root_user(value) if startswith(lower(sprintf("%v", [value])), "root:")

# The base's own choice, read from the file as it sits on disk rather than from
# the merge — the merge has already resolved the conflict this rule reports.
_base_runs_unprivileged(name) if {
	some cf in input.compose_files
	not cf.is_override
	service := cf.services[name]
	is_object(service)
	user := service.user
	not _root_user(user)
}

violations contains violation if {
	some cf in input.compose_files
	cf.is_override

	some name, service in cf.services
	is_object(service)
	_root_user(service.user)
	_base_runs_unprivileged(name)

	violation := {
		"rule": "compose_override_weakens_user",
		"severity": "high",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Override runs '%v' as root, undoing the unprivileged user the base file sets. The override is what actually runs.", [name]),
		"discriminator": name,
	}
}
