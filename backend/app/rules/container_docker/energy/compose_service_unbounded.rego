# METADATA
# title: Service has no resource limit and no log rotation
# description: "A Compose service declares no memory or CPU limit and no log rotation. Both are unbounded growth with the same ending: a container that can take the whole host's memory starves everything beside it, and the default json-file log driver never rotates, so one chatty service fills the disk and stops every other one. Reported together, once per service, because both are answers to the same question — what is this container allowed to consume — and both are one line."
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         worker:
#           image: ghcr.io/example/worker:2.0.0
#     good: |
#       services:
#         worker:
#           image: ghcr.io/example/worker:2.0.0
#           mem_limit: 512m
#           logging:
#             driver: json-file
#             options:
#               max-size: "10m"
#               max-file: "3"
#     fix: |
#       Set a memory limit from the service's measured peak plus headroom, and set logging.options.max-size and max-file. Where the host already ships logs elsewhere — journald, an agent, a cloud driver — naming that driver is itself the answer and this leaves it alone.
package greensecops.container_docker.energy.compose_service_unbounded

import rego.v1

# Replaces `compose_missing_resource_limits` and `compose_unbounded_log_files`.
# See `compose_service_not_hardened` for the reasoning; this is the same
# consolidation on the energy axis, kept separate from the security pair so
# each finding still scores against the axis it belongs to.

_is_runnable(service) if service.image

_is_runnable(service) if service.build

_has_limit(service) if service.mem_limit

_has_limit(service) if service.cpus

_has_limit(service) if {
	limits := service.deploy.resources.limits
	count(limits) > 0
}

_bounds_logs(service) if object.get(object.get(service.logging, "options", {}), "max-size", null) != null

# Any driver other than the unrotated default is delegating retention
# elsewhere, which is a deliberate answer to the same question. The `local`
# driver rotates by default, so naming it is itself a bound.
_bounds_logs(service) if {
	driver := service.logging.driver
	is_string(driver)
	not driver == "json-file"
}

# `_has_limit` and `_bounds_logs` are partial rules: true or *undefined*, never
# false. Putting them in an object literal makes the literal itself undefined,
# so the missing list is built by negation instead, in a fixed order so the
# message reads the same way every time.
_settings := ["a memory or CPU limit", "log rotation"]

_satisfied(service, "a memory or CPU limit") if _has_limit(service)

_satisfied(service, "log rotation") if _bounds_logs(service)

_missing(service) := [setting |
	some setting in _settings
	not _satisfied(service, setting)
]

violations contains violation if {
	some cf in input.effective_compose_files
	some name, service in cf.services
	is_object(service)
	_is_runnable(service)

	missing := _missing(service)
	count(missing) > 0

	violation := {
		"rule": "compose_service_unbounded",
		"severity": "low",
		"category": "energy",
		"file_path": object.get(service, "__docker_file", object.get(cf, "__docker_file", "")),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' declares no %v, so it can grow until the host runs out. Bound it: a limit from measured peak, and logging.options.max-size.", [name, concat(" and no ", missing)]),
		"context": concat(", ", missing),
		"discriminator": name,
	}
}
