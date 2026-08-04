package greensecops.container_docker.reliability.compose_dependency_without_healthcheck_test

import data.greensecops.container_docker.reliability.compose_dependency_without_healthcheck as dependency_unhealthy
import rego.v1

# Compose accepts `depends_on` as a list of names or as a map keyed by name
# with a condition; both spellings have to be understood.

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"is_override": false,
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

_healthcheck := {"test": ["CMD-SHELL", "pg_isready -U postgres"], "interval": "5s"}

test_violation_when_a_depended_on_service_has_no_healthcheck if {
	violations := dependency_unhealthy.violations with input as _compose({
		"db": _service({}),
		"api": _service({"depends_on": {"db": {"condition": "service_healthy"}}}),
	})
	count(violations) == 1
	some v in violations
	v.service_name == "db"
}

test_violation_for_the_list_form_of_depends_on if {
	violations := dependency_unhealthy.violations with input as _compose({
		"db": _service({}),
		"api": _service({"depends_on": ["db"]}),
	})
	count(violations) == 1
}

test_no_violation_when_the_dependency_has_a_healthcheck if {
	violations := dependency_unhealthy.violations with input as _compose({
		"db": _service({"healthcheck": _healthcheck}),
		"api": _service({"depends_on": {"db": {"condition": "service_healthy"}}}),
	})
	count(violations) == 0
}

# A service nothing depends on is not this rule's concern — missing_healthcheck
# and the runtime rules cover images generally.
test_no_violation_for_a_service_nobody_depends_on if {
	violations := dependency_unhealthy.violations with input as _compose({
		"api": _service({}),
		"worker": _service({}),
	})
	count(violations) == 0
}

# A dependency declared in another file is not something this document can
# answer for.
test_no_violation_when_the_dependency_is_not_defined_here if {
	violations := dependency_unhealthy.violations with input as _compose({"api": _service({"depends_on": ["external-db"]})})
	count(violations) == 0
}

test_no_violation_in_an_override_fragment if {
	violations := dependency_unhealthy.violations with input as {"compose_files": [{
		"__docker_file": "compose.override.yml",
		"is_override": true,
		"services": {
			"db": _service({}),
			"api": _service({"depends_on": ["db"]}),
		},
	}]}
	count(violations) == 0
}

test_no_violation_for_a_null_service if {
	violations := dependency_unhealthy.violations with input as _compose({
		"db": null,
		"api": _service({"depends_on": ["db"]}),
	})
	count(violations) == 0
}

# One finding per depended-on service, however many things depend on it.
test_one_finding_per_dependency_not_per_dependent if {
	violations := dependency_unhealthy.violations with input as _compose({
		"db": _service({}),
		"api": _service({"depends_on": ["db"]}),
		"worker": _service({"depends_on": ["db"]}),
	})
	count(violations) == 1
}

test_each_unhealthy_dependency_is_its_own_finding if {
	violations := dependency_unhealthy.violations with input as _compose({
		"db": _service({}),
		"cache": _service({}),
		"queue": _service({"healthcheck": _healthcheck}),
		"api": _service({"depends_on": ["db", "cache", "queue"]}),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
