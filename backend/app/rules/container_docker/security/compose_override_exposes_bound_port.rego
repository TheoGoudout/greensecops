# METADATA
# title: Override publishes a port the base bound to localhost
# description: A Compose override publishes a port on every interface for a service whose base definition binds it to the loopback address. Compose *appends* port mappings across the merge rather than replacing them, so the loopback binding is not superseded — both are published, and the wide one is the one that matters. The loopback binding was somebody being careful, and it is worth knowing that care is being undone, particularly since Docker publishes ports by writing iptables rules that bypass a host firewall rather than sitting behind it.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       # compose.override.yml
#       services:
#         db:
#           ports:
#             - "5432:5432"
#     good: |
#       # compose.override.yml — keep the interface explicit
#       services:
#         db:
#           ports:
#             - "127.0.0.1:15432:5432"
#     fix: |
#       Keep the host address in the mapping. If the port needs to be reachable from another machine, say which one by binding to that interface's address rather than to all of them, and remember that a host firewall will not see the traffic.
package greensecops.container_docker.security.compose_override_exposes_bound_port

import rego.v1

_parts(mapping) := split(sprintf("%v", [mapping]), ":")

# "5432:5432" and "5432" publish on every interface; "127.0.0.1:5432:5432"
# does not. Three parts means the first is a host address.
_container_port(mapping) := port if {
	parts := _parts(mapping)
	count(parts) == 3
	port := parts[2]
}

_container_port(mapping) := port if {
	parts := _parts(mapping)
	count(parts) == 2
	port := parts[1]
}

# A bare "5432" publishes that container port on every interface, on a host
# port Docker picks. The address is still every address, so it undoes a
# loopback binding just as squarely as the two-part form.
_container_port(mapping) := port if {
	parts := _parts(mapping)
	count(parts) == 1
	port := parts[0]
}

_host_address(mapping) := address if {
	parts := _parts(mapping)
	count(parts) == 3
	address := parts[0]
}

_is_loopback(address) if startswith(address, "127.")

_is_loopback(address) if address == "::1"

_is_loopback(address) if address == "localhost"

# Ports compose_port_bound_to_all_interfaces already reports wherever it finds
# them. Repeating them would put two findings on one line. What is left to this
# rule is the case that one does not cover — an admin UI, a debug listener or a
# metrics endpoint the base deliberately kept on loopback, where nothing else
# fires at all.
_reported_elsewhere := {
	"1433", "3306", "5432", "5672",
	"6379", "9200", "11211", "27017",
}

_base_binds_to_loopback(name, container_port) if {
	some cf in input.compose_files
	not cf.is_override
	service := cf.services[name]
	is_object(service)
	some mapping in service.ports
	_container_port(mapping) == container_port
	_is_loopback(_host_address(mapping))
}

violations contains violation if {
	some cf in input.compose_files
	cf.is_override

	some name, service in cf.services
	is_object(service)

	some mapping in service.ports
	container_port := _container_port(mapping)
	not container_port in _reported_elsewhere

	# A mapping with no host address publishes on every interface.
	not _host_address(mapping)

	_base_binds_to_loopback(name, container_port)

	violation := {
		"rule": "compose_override_exposes_bound_port",
		"severity": "high",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Override publishes '%v' port %v on every interface, alongside the loopback binding the base file sets — Compose appends port mappings rather than replacing them, so both apply.", [name, container_port]),
		"discriminator": sprintf("%v-%v", [name, container_port]),
	}
}
