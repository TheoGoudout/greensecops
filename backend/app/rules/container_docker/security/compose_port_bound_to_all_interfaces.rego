# METADATA
# title: Datastore port published on every interface
# description: A Compose service publishes a well-known datastore port without naming a host interface, so Docker binds it to 0.0.0.0 and the database is reachable from anywhere that can route to the host. Docker's port publishing writes its own iptables rules, which sit in front of most host firewalls — so a port that looks closed from ufw or firewalld is in fact open. On a CI runner or a developer machine on a shared network this exposes a database that is almost always running with development credentials.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         db:
#           image: postgres:18
#           ports:
#             - "5432:5432"
#     good: |
#       services:
#         db:
#           image: postgres:18
#           ports:
#             - "127.0.0.1:5432:5432"
#     fix: |
#       Prefix the mapping with 127.0.0.1 so only the host can reach it. Better still, drop the mapping entirely — services on the same Compose network reach each other by service name without any port being published at all.
package greensecops.container_docker.security.compose_port_bound_to_all_interfaces

import rego.v1

# Scoped to datastores rather than every published port. A web service on 8080
# is usually published on purpose; a database almost never is, and these are
# the ports where an unauthenticated default is the norm.
_datastore_ports := {
	"1433": "SQL Server",
	"27017": "MongoDB",
	"3306": "MySQL",
	"5432": "PostgreSQL",
	"5672": "RabbitMQ",
	"6379": "Redis",
	"9200": "Elasticsearch",
	"11211": "Memcached",
}

# Compose long syntax. `host_ip` unset means every interface, same as the short
# form without a prefix.
_published(entry) := {"host_port": host_port, "host_ip": object.get(entry, "host_ip", "")} if {
	is_object(entry)
	host_port := format_int(entry.published, 10)
}

_published(entry) := {"host_port": host_port, "host_ip": object.get(entry, "host_ip", "")} if {
	is_object(entry)
	is_string(entry.published)
	host_port := entry.published
}

# Short syntax, as a string: "5432:5432", "127.0.0.1:5432:5432", "5432".
_published(entry) := {"host_port": parts[0], "host_ip": ""} if {
	is_string(entry)
	parts := split(entry, ":")
	count(parts) == 2
}

_published(entry) := {"host_port": parts[1], "host_ip": parts[0]} if {
	is_string(entry)
	parts := split(entry, ":")
	count(parts) == 3
}

# A bare "5432" publishes the container port on a random host port, which is
# still every interface.
_published(entry) := {"host_port": entry, "host_ip": ""} if {
	is_string(entry)
	not contains(entry, ":")
}

# Numeric short syntax — YAML parses an unquoted `- 5432` as an integer.
_published(entry) := {"host_port": format_int(entry, 10), "host_ip": ""} if {
	is_number(entry)
}

_binds_all_interfaces(host_ip) if host_ip == ""

_binds_all_interfaces(host_ip) if host_ip == "0.0.0.0"

_binds_all_interfaces(host_ip) if host_ip == "::"

violations contains violation if {
	some cf in input.compose_files
	some name, service in cf.services
	is_object(service)

	some entry in service.ports
	mapping := _published(entry)
	service_label := _datastore_ports[mapping.host_port]
	_binds_all_interfaces(mapping.host_ip)

	violation := {
		"rule": "compose_port_bound_to_all_interfaces",
		"severity": "medium",
		"category": "security",
		"file_path": object.get(cf, "__docker_file", ""),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Service '%v' publishes the %v port %v on every interface. Docker's own iptables rules sit in front of the host firewall, so this is reachable even where the firewall says otherwise — bind it to 127.0.0.1 or drop the mapping.", [name, service_label, mapping.host_port]),
		"context": sprintf("%v", [entry]),
		"discriminator": sprintf("%v:%v", [name, mapping.host_port]),
	}
}
