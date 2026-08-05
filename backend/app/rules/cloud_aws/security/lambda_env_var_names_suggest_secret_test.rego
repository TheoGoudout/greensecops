package greensecops.cloud_aws.security.lambda_env_var_names_suggest_secret_test

import data.greensecops.cloud_aws.security.lambda_env_var_names_suggest_secret as env_secret
import rego.v1

# The collector stores variable names only — never values — so these fixtures
# are the whole of what the rule can ever see.

_fn(environment_names) := {"lambda_functions": [{
	"name": "checkout",
	"region": "eu-west-1",
	"runtime": "python3.12",
	"environment_names": environment_names,
	"vpc_configured": true,
	"tracing_enabled": true,
}]}

test_violation_for_a_password_variable if {
	violations := env_secret.violations with input as _fn(["DATABASE_PASSWORD"])
	count(violations) == 1
	some v in violations
	v.resource_id == "checkout"
	v.severity == "high"
}

test_violation_for_a_token_variable if {
	violations := env_secret.violations with input as _fn(["GITHUB_TOKEN"])
	count(violations) == 1
}

test_violation_for_the_underscored_api_key_spelling if {
	violations := env_secret.violations with input as _fn(["STRIPE_API_KEY"])
	count(violations) == 1
}

test_violation_for_the_unseparated_apikey_spelling if {
	violations := env_secret.violations with input as _fn(["STRIPE_APIKEY"])
	count(violations) == 1
}

test_matching_is_case_insensitive if {
	violations := env_secret.violations with input as _fn(["db_password"])
	count(violations) == 1
}

# A name pointing at where the secret lives is the recommended fix, so firing
# on it would report the correct configuration.
test_no_violation_for_a_secret_arn_reference if {
	violations := env_secret.violations with input as _fn(["DB_SECRET_ARN"])
	count(violations) == 0
}

test_no_violation_for_a_parameter_path_reference if {
	violations := env_secret.violations with input as _fn(["API_KEY_PATH"])
	count(violations) == 0
}

test_no_violation_for_an_ordinary_variable if {
	violations := env_secret.violations with input as _fn(["LOG_LEVEL", "REGION"])
	count(violations) == 0
}

test_no_violation_for_a_function_with_no_environment if {
	violations := env_secret.violations with input as _fn([])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := env_secret.violations with input as {"lambda_functions": []}
	count(violations) == 0
}

test_the_message_names_the_variable if {
	violations := env_secret.violations with input as _fn(["DATABASE_PASSWORD"])
	some v in violations
	contains(v.message, "DATABASE_PASSWORD")
}

test_each_suspect_variable_is_its_own_finding if {
	violations := env_secret.violations with input as _fn([
		"DATABASE_PASSWORD",
		"GITHUB_TOKEN",
		"LOG_LEVEL",
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
