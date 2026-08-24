package greensecops.container_docker.security.compose_hardcoded_secret_test

import data.greensecops.container_docker.security.compose_hardcoded_secret
import rego.v1

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

_real_secret := "J8rQ2pV7xL4mN9tKs3Wf6BzYcH1dAe5g"

test_violation_for_literal_password_in_mapping_form if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"POSTGRES_PASSWORD": _real_secret}})})
	count(violations) == 1
	some v in violations
	v.context == "POSTGRES_PASSWORD"
}

test_violation_for_literal_password_in_list_form if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": [concat("=", ["POSTGRES_PASSWORD", _real_secret])]})})
	count(violations) == 1
}

# A recognised credential format is reported on sight, however short.
test_violation_for_a_known_credential_format if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"AWS_ACCESS_KEY": "AKIAIOSFODNN7EXAMPLE"}})})
	count(violations) == 1
}

# The development fixture this rule used to report at high severity.
test_no_violation_for_a_development_placeholder if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"POSTGRES_PASSWORD": "changethis"}})})
	count(violations) == 0
}

test_no_violation_for_a_short_test_value if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": {"POSTGRES_PASSWORD": "hunter2"}})})
	count(violations) == 0
}

# `split(entry, "=")` with `count == 2` dropped every base64 value with
# padding, which is most of them.
test_violation_for_a_list_value_containing_an_equals_sign if {
	violations := compose_hardcoded_secret.violations with input as _compose({"db": _service({"environment": ["API_TOKEN=aGVsbG8gd29ybGQgdGhpcyBpcyBhIHNlY3JldA=="]})})
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
		"POSTGRES_PASSWORD": _real_secret,
		"API_TOKEN": "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
	}})})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
