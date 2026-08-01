# METADATA
# title: Compose service declares no restart policy
# description: A service sets no restart policy, so Docker leaves it stopped after a crash or a host reboot. The default is "no" — a service that dies at 3am stays dead until someone notices.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#     good: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#           restart: unless-stopped
#     fix: |
#       Set restart: unless-stopped for long-running services (or deploy.restart_policy under Swarm). Leave it unset only for one-shot jobs and migration containers, where restarting on exit is exactly wrong.
package greensecops.container_docker.reliability.compose_missing_restart_policy

import rego.v1

_is_runnable(service) if service.image

_is_runnable(service) if service.build

_has_restart_policy(service) if {
	policy := service.restart
	policy != "no"
}

# An explicit `restart: "no"` is a considered choice, not the unconsidered
# default this rule is about — it is the correct setting for a one-shot
# migration or seed container, where restarting on exit would be actively
# wrong (this rule's own fix text says so). Absence still fires.
_has_restart_policy(service) if service.restart == "no"

_has_restart_policy(service) if service.deploy.restart_policy

violations contains violation if {
	some cf in input.compose_files

	# An override fragment inherits what it does not restate from the base
	# file, so absence here proves nothing. See merge.is_override_file.
	not cf.is_override
	some name, service in cf.services
	is_object(service)
	_is_runnable(service)
	not _has_restart_policy(service)
	violation := {
		"rule": "compose_missing_restart_policy",
		"severity": "medium",
		"category": "reliability",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' has no restart policy, so it stays down after a crash or host reboot.", [name]),
		"discriminator": name,
	}
}
