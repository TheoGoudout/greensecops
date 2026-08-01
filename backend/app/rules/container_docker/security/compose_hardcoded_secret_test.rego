package greensecops.container_docker.security.compose_hardcoded_secret_test

import data.greensecops.container_docker.security.compose_hardcoded_secret
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_for_literal_password_in_mapping_form if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"POSTGRES_PASSWORD": "hunter2"}})})
	count(violations) == 1
	some v in violations
	v.context == "POSTGRES_PASSWORD"
}

test_violation_for_literal_password_in_list_form if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": ["POSTGRES_PASSWORD=hunter2"]})})
	count(violations) == 1
}

test_no_violation_when_interpolated if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"POSTGRES_PASSWORD": "${POSTGRES_PASSWORD}"}})})
	count(violations) == 0
}

test_no_violation_when_interpolated_with_default if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:?required}"}})})
	count(violations) == 0
}

test_no_violation_for_non_secret_variable if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"POSTGRES_DB": "app"}})})
	count(violations) == 0
}

test_two_secrets_in_one_service_are_distinct_findings if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {
		"POSTGRES_PASSWORD": "hunter2",
		"API_TOKEN": "abc123",
	}})})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
