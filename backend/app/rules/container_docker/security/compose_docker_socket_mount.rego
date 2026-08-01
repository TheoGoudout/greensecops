# METADATA
# title: Docker socket mounted into a container
# description: A service bind-mounts /var/run/docker.sock. Anything that can talk to the Docker socket can start a container with the host filesystem mounted, so this grants the container root on the host — it is privilege escalation regardless of which user the container runs as.
# custom:
#   severity: critical
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         ci:
#           image: ghcr.io/example/runner:2.1.0
#           volumes:
#             - /var/run/docker.sock:/var/run/docker.sock
#     good: |
#       services:
#         ci:
#           image: ghcr.io/example/runner:2.1.0
#           environment:
#             DOCKER_HOST: tcp://docker-proxy:2375
#     fix: |
#       Route through a filtering socket proxy that exposes only the endpoints the workload needs, or use a rootless builder such as BuildKit or Kaniko. If the container only builds images, a dedicated build service is safer than handing it the daemon.
package greensecops.container_docker.security.compose_docker_socket_mount

import rego.v1

_socket_path := "/var/run/docker.sock"

# Short syntax: "host:container[:mode]". Long syntax: a mapping with `source`.
_mounts_socket(service) if {
	some volume in service.volumes
	is_string(volume)
	startswith(volume, _socket_path)
}

_mounts_socket(service) if {
	some volume in service.volumes
	is_object(volume)
	object.get(volume, "source", "") == _socket_path
}

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)
	_mounts_socket(service)
	violation := {
		"rule": "compose_docker_socket_mount",
		"severity": "critical",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' mounts the Docker socket, which is equivalent to giving it root on the host.", [name]),
		"discriminator": name,
	}
}
