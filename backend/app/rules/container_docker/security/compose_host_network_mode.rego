# METADATA
# title: Compose service uses host networking
# description: A service sets network_mode host, so it shares the host's network namespace. Every port it opens is bound on the host whether or not it was published, it can reach services listening on the host loopback, and Compose's network-level isolation between services no longer applies.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#           network_mode: host
#     good: |
#       services:
#         api:
#           image: ghcr.io/example/api:1.2.0
#           ports:
#             - "127.0.0.1:8080:8080"
#     fix: |
#       Remove network_mode and publish only the ports the service needs, binding them to a specific interface. Host networking is occasionally required for protocols that embed addresses (mDNS, some VPN tooling) — where it is genuinely needed, document why next to the setting.
package greensecops.container_docker.security.compose_host_network_mode

import rego.v1

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)
	lower(object.get(service, "network_mode", "")) == "host"
	violation := {
		"rule": "compose_host_network_mode",
		"severity": "high",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' uses host networking, so it shares the host network namespace and bypasses port publishing.", [name]),
		"discriminator": name,
	}
}
