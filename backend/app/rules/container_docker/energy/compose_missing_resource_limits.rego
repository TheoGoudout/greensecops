# METADATA
# title: Compose service declares no resource limits
# description: A service sets neither a memory nor a CPU limit, so it may consume whatever the host has. One runaway container starves every other service on the box, and without a declared ceiling there is no signal of what the workload actually needs — capacity ends up over-provisioned by guesswork.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         worker:
#           image: ghcr.io/example/worker:3.0.1
#     good: |
#       services:
#         worker:
#           image: ghcr.io/example/worker:3.0.1
#           deploy:
#             resources:
#               limits:
#                 cpus: "1.5"
#                 memory: 512M
#     fix: |
#       Declare limits under deploy.resources.limits (or the mem_limit/cpus shorthand). Measure the workload's real peak first — a limit set far above actual usage documents nothing, and one set below it turns into OOM kills.
package greensecops.container_docker.energy.compose_missing_resource_limits

import rego.v1

# Only services that actually run a container. A service that is purely an
# anchor for `extends` or carries only build config has nothing to limit.
_is_runnable(service) if service.image

_is_runnable(service) if service.build

_has_limit(service) if service.mem_limit

_has_limit(service) if service.cpus

_has_limit(service) if {
	limits := service.deploy.resources.limits
	count(limits) > 0
}

# `effective_compose_files` is one document per configuration, with a base and
# its override already merged — absence is only meaningful about a complete
# configuration, so that is what this rule reads. The per-service
# `__docker_file` is preferred over the document's because a service the
# override introduces is not in the base file the merged document is named for.
violations contains violation if {
	some cf in input.effective_compose_files
	some name, service in cf.services
	is_object(service)
	_is_runnable(service)
	not _has_limit(service)
	violation := {
		"rule": "compose_missing_resource_limits",
		"severity": "low",
		"category": "energy",
		"file_path": object.get(service, "__docker_file", object.get(cf, "__docker_file", "")),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' declares no memory or CPU limit, so it can consume the whole host.", [name]),
		"discriminator": name,
	}
}
