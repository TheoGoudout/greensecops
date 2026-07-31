# METADATA
# title: depends_on used without a health condition
# description: A service declares depends_on in the short list form, which only waits for the dependency's container to be created — not for the process inside it to be ready. The dependent service starts against a database that is still initialising, fails its first connection, and relies on the restart policy to eventually paper over the race.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#           depends_on:
#             - db
#     good: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#           depends_on:
#             db:
#               condition: service_healthy
#     fix: |
#       Switch to the long form with condition: service_healthy and give the dependency a healthcheck. Application-level retry is still worth having — startup ordering is not the only way a dependency goes away — but it should not be the only thing standing between the service and a cold-start failure.
package greensecops.container_docker.reliability.compose_depends_on_without_condition

import rego.v1

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)

	# The short form is a sequence; the long form is a mapping of
	# dependency -> {condition: ...}.
	is_array(service.depends_on)
	count(service.depends_on) > 0
	violation := {
		"rule": "compose_depends_on_without_condition",
		"severity": "low",
		"category": "reliability",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' uses the short depends_on form, which waits for container creation rather than readiness. Use condition: service_healthy.", [name]),
		"discriminator": name,
	}
}
