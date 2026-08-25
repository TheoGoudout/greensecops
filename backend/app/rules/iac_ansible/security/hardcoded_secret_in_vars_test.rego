package greensecops.iac_ansible.security.hardcoded_secret_in_vars_test

import data.greensecops.iac_ansible.security.hardcoded_secret_in_vars as rule
import rego.v1

_file(vars) := {"files": [{
	"__ansible_file": "group_vars/all.yml",
	"kind": "vars",
	"vars": vars,
}]}

test_violation_for_a_high_entropy_literal if {
	violations := rule.violations with input as _file({
		"postgres_password": "S6xQ2vLm9TpKd4Rw8YnZ",
		"__lines__": {"postgres_password": 4},
	})
	count(violations) == 1
	some v in violations
	v.line_start == 4
	v.discriminator == "postgres_password"
}

test_violation_for_a_known_credential_format if {
	violations := rule.violations with input as _file({"aws_access_key": "AKIAIOSFODNN7EXAMPLE"})
	count(violations) == 1
}

test_no_violation_for_a_templated_value if {
	violations := rule.violations with input as _file({"postgres_password": "{{ lookup('env', 'PG') }}"})
	count(violations) == 0
}

test_no_violation_for_a_placeholder if {
	violations := rule.violations with input as _file({"postgres_password": "changethischangethis"})
	count(violations) == 0
}

test_no_violation_for_a_short_value if {
	violations := rule.violations with input as _file({"api_token": "abc123"})
	count(violations) == 0
}

# The trap this rule exists to avoid: a list of secret *names* is not a secret.
test_no_violation_for_a_list_of_secret_names if {
	violations := rule.violations with input as _file({"required_secrets": [
		"FIRST_SUPERUSER_PASSWORD",
		"GITHUB_CLIENT_SECRET",
	]})
	count(violations) == 0
}

test_no_violation_for_a_plural_name_holding_a_string if {
	violations := rule.violations with input as _file({"required_secrets": "S6xQ2vLm9TpKd4Rw8YnZ"})
	count(violations) == 0
}

test_no_violation_for_an_unrelated_name if {
	violations := rule.violations with input as _file({"release_identifier": "S6xQ2vLm9TpKd4Rw8YnZ"})
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"env": {"PASSWORD": "S6xQ2vLm9TpKd4Rw8YnZ"}}
	count(violations) == 0
}
