package greensecops.container_docker.security.secret_in_build_arg_test

import data.greensecops.container_docker.security.secret_in_build_arg
import rego.v1

_df(instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [],
	"instructions": instructions,
}]}

_inst(keyword, value) := {
	"instruction": keyword,
	"value": value,
	"stage": 0,
	"__start_line__": 2,
	"__end_line__": 2,
}

test_violation_for_hardcoded_arg_token if {
	violations := secret_in_build_arg.violations with input as _df([_inst("ARG", "NPM_TOKEN=npm_A1b2C3d4")])
	count(violations) == 1
	some v in violations
	v.discriminator == "NPM_TOKEN"
}

test_violation_for_hardcoded_env_password if {
	violations := secret_in_build_arg.violations with input as _df([_inst("ENV", "DB_PASSWORD=hunter2")])
	count(violations) == 1
}

test_violation_for_quoted_value if {
	violations := secret_in_build_arg.violations with input as _df([_inst("ENV", "API_KEY=\"sk-prod-abc123\"")])
	count(violations) == 1
}

# An ARG with no default is the correct way to accept a build-time credential.
test_no_violation_for_arg_without_default if {
	violations := secret_in_build_arg.violations with input as _df([_inst("ARG", "NPM_TOKEN")])
	count(violations) == 0
}

test_no_violation_when_value_references_a_variable if {
	violations := secret_in_build_arg.violations with input as _df([_inst("ENV", "DB_PASSWORD=$DB_PASSWORD_ARG")])
	count(violations) == 0
}

test_no_violation_for_non_secret_name if {
	violations := secret_in_build_arg.violations with input as _df([_inst("ENV", "NODE_ENV=production")])
	count(violations) == 0
}

test_two_secrets_in_one_instruction_are_distinct_findings if {
	violations := secret_in_build_arg.violations with input as _df([_inst("ENV", "API_KEY=abc DB_PASSWORD=def")])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
