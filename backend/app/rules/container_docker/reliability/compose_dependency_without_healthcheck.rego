# METADATA
# title: Depended-on service declares no healthcheck
# description: A Compose service other services depend on has no healthcheck, so nothing can wait for it to be ready — only for its container to exist. The dependents start against a database that is still recovering or an API that has not bound its port yet, and the resulting failure is timing-dependent, which is why it shows up in CI far more often than on a developer's machine where the images are already warm. The companion compose_depends_on_without_condition rule looks at the dependent's side of the same problem.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       services:
#         db:
#           image: postgres:18
#         api:
#           image: api:1.0
#           depends_on:
#             db:
#               condition: service_healthy
#     good: |
#       services:
#         db:
#           image: postgres:18
#           healthcheck:
#             test: ["CMD-SHELL", "pg_isready -U postgres"]
#             interval: 5s
#             retries: 10
#         api:
#           image: api:1.0
#           depends_on:
#             db:
#               condition: service_healthy
#     fix: |
#       Give the depended-on service a healthcheck that probes what its dependents actually use — a query for a database, a served path for an API. Without one, service_healthy cannot be satisfied and service_started is the only condition available, which is not readiness.
package greensecops.container_docker.reliability.compose_dependency_without_healthcheck

import rego.v1

# `depends_on` is either a list of names or a map keyed by name.
_dependency_names(service) := {name | some name in service.depends_on} if {
	is_array(service.depends_on)
}

_dependency_names(service) := {name | some name, _ in service.depends_on} if {
	is_object(service.depends_on)
}

# Only the dependencies that are actually waited on for *readiness*. The long
# form carries a condition, and `service_completed_successfully` is the correct
# way to depend on a one-shot container — a migration job that runs and exits
# cannot have a meaningful healthcheck, and asking for one on this
# repository's own `prestart` service was asking for something wrong.
_waits_for_readiness(service, name) if {
	is_array(service.depends_on)
	name in {n | some n in service.depends_on}
}

_waits_for_readiness(service, name) if {
	is_object(service.depends_on)
	entry := service.depends_on[name]
	not is_object(entry)
}

_waits_for_readiness(service, name) if {
	is_object(service.depends_on)
	entry := service.depends_on[name]
	is_object(entry)
	object.get(entry, "condition", "service_started") != "service_completed_successfully"
}

_depended_on(cf) := {name |
	some _, service in cf.services
	is_object(service)
	some name in _dependency_names(service)
	_waits_for_readiness(service, name)
}

# `effective_compose_files` is one document per configuration, with a base and
# its override already merged — absence is only meaningful about a complete
# configuration, so that is what this rule reads. The per-service
# `__docker_file` is preferred over the document's because a service the
# override introduces is not in the base file the merged document is named for.
violations contains violation if {
	some cf in input.effective_compose_files

	some name in _depended_on(cf)

	# Only judge a service this file actually defines; a dependency on one
	# declared elsewhere is not something this document can answer for.
	service := cf.services[name]
	is_object(service)
	not service.healthcheck

	violation := {
		"rule": "compose_dependency_without_healthcheck",
		"severity": "medium",
		"category": "reliability",
		"file_path": object.get(service, "__docker_file", object.get(cf, "__docker_file", "")),
		"service_name": name,
		"line_start": object.get(service, "__start_line__", null),
		"line_end": object.get(service, "__end_line__", null),
		"message": sprintf("Other services depend on '%v', but it has no healthcheck — so they can only wait for its container to exist, not for it to be ready.", [name]),
		"discriminator": name,
	}
}
