# METADATA
# title: Service has no log rotation configured
# description: A Compose service does not bound its log file. Docker's default json-file driver has no rotation at all, so the file grows until the disk is full — and because it is the daemon writing it, the container itself sees no error and keeps running while everything else on the host starts failing to write. It is a slow failure that surfaces days later on long-lived hosts, and on CI runners it shows up as the disk-pressure the runner_disk_pressure rule reports without saying why.
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
#           logging:
#             driver: json-file
#             options:
#               max-size: "10m"
#               max-file: "3"
#     fix: |
#       Set logging.options.max-size and max-file on the service, or configure the daemon's default in /etc/docker/daemon.json so every container inherits a bound. A service that logs to a collector instead can set the driver to that collector, which also satisfies this.
package greensecops.container_docker.energy.compose_unbounded_log_files

import rego.v1

_is_runnable(service) if service.image

_is_runnable(service) if service.build

_bounds_logs(service) if object.get(object.get(service.logging, "options", {}), "max-size", null) != null

# Any driver other than the unrotated default is delegating retention
# elsewhere, which is a deliberate answer to the same question.
_bounds_logs(service) if {
	driver := service.logging.driver
	is_string(driver)
	not driver in {"json-file", "local"}
}

# The `local` driver rotates by default, so naming it is itself a bound.
_bounds_logs(service) if service.logging.driver == "local"

violations contains violation if {
	some cf in input.compose_files

	# An override fragment inherits what it does not restate, so absence here
	# proves nothing. See merge.is_override_file.
	not cf.is_override

	some name, service in cf.services
	is_object(service)
	_is_runnable(service)
	not _bounds_logs(service)

	violation := {
		"rule": "compose_unbounded_log_files",
		"severity": "low",
		"category": "energy",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' has no log rotation, and the default json-file driver never rotates — the log grows until the host's disk is full. Set logging.options.max-size and max-file.", [name]),
		"discriminator": name,
	}
}
