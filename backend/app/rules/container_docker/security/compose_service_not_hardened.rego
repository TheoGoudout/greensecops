# METADATA
# title: Service runs without the container hardening flags
# description: "A Compose service does not set read_only and does not set no-new-privileges. Both are one-line settings that remove a whole class of post-compromise move: a writable root filesystem lets a process that gets execution drop a binary and persist across a restart, and without no-new-privileges a setuid binary already in the image can still raise privilege. Neither changes what the service does when it is behaving. Reported together, once per service, because they are the same decision — 'was this container hardened' — and the answer is normally the same for both."
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.4.0
#     good: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.4.0
#           read_only: true
#           tmpfs:
#             - /tmp
#           security_opt:
#             - no-new-privileges:true
#     fix: |
#       Add `read_only: true` with a tmpfs for the paths the process genuinely writes, and `no-new-privileges:true` under security_opt. Start with no-new-privileges — it has no operational cost at all — then add read_only and let the first failed start tell you which paths need a tmpfs.
package greensecops.container_docker.security.compose_service_not_hardened

import rego.v1

# Replaces `compose_missing_read_only_filesystem` and
# `compose_missing_no_new_privileges`, which were the same rule asked twice.
# Between them they produced two `low` findings for every service in every
# Compose file — 40 of the 78 findings on this repository's own nine Docker
# files — and no configuration satisfies one without the other being the
# obvious next line. One finding that names what is missing carries the same
# information at half the volume.
#
# The energy-axis pair (`compose_service_unbounded`) is the same consolidation
# for log rotation and resource limits. They stay separate from these because
# the axis a finding scores against is what the product is for.

_is_runnable(service) if service.image

_is_runnable(service) if service.build

# A privileged container ignores both flags, and `compose_privileged_container`
# reports the far larger problem that supersedes them.
_is_privileged(service) if service.privileged == true

_sets_no_new_privileges(service) if {
	some option in service.security_opt
	is_string(option)
	regex.match(`(?i)^no-new-privileges\s*[:=]\s*(true|1)$`, trim_space(option))
}

# Built by negation rather than from an object literal: `service.read_only` is
# undefined when the key is absent, which would make the literal itself
# undefined. Fixed order so the message reads the same way every time.
_settings := ["read_only: true", "no-new-privileges:true under security_opt"]

_satisfied(service, "read_only: true") if service.read_only == true

_satisfied(service, "no-new-privileges:true under security_opt") if _sets_no_new_privileges(service)

_missing(service) := [setting |
	some setting in _settings
	not _satisfied(service, setting)
]

# `effective_compose_files` is one document per configuration, with a base and
# its override already merged — absence is only meaningful about a complete
# configuration, so that is what this reads. The per-service `__docker_file` is
# preferred over the document's because a service the override introduces is
# not in the base file the merged document is named for.
violations contains violation if {
	some cf in input.effective_compose_files
	some name, service in cf.services
	is_object(service)
	_is_runnable(service)
	not _is_privileged(service)

	missing := _missing(service)
	count(missing) > 0

	violation := {
		"rule": "compose_service_not_hardened",
		"severity": "low",
		"category": "security",
		"file_path": object.get(service, "__docker_file", object.get(cf, "__docker_file", "")),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' is missing %v. Neither changes what the service does when it is behaving; both remove a move an attacker has once they are inside it.", [name, concat(" and ", missing)]),
		"context": concat(", ", missing),
		"discriminator": name,
	}
}
