package greensecops.iac_terraform.security.hardcoded_credentials_in_tf_test

import data.greensecops.iac_terraform.security.hardcoded_credentials_in_tf as hardcoded_credentials
import rego.v1

# The rule walks every string value in a resource, so a key is found wherever
# it was written -- a top-level attribute, a nested block, or a tag value.

_res(res_type, attrs) := {"resource": [{res_type: {"main": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 9},
	attrs,
)}}]}

test_violation_for_an_access_key_id if {
	violations := hardcoded_credentials.violations with input as _res("aws_instance", {"user_data": "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_instance.main"
	v.severity == "critical"
}

test_violation_when_nested_inside_a_block if {
	violations := hardcoded_credentials.violations with input as _res("aws_instance", {"tags": {"Owner": "AKIAIOSFODNN7EXAMPLE"}})
	count(violations) == 1
}

test_no_violation_for_a_variable_reference if {
	violations := hardcoded_credentials.violations with input as _res("aws_instance", {"user_data": "export AWS_ACCESS_KEY_ID=${var.access_key}"})
	count(violations) == 0
}

# ASIA is a temporary session key and AKIA is the long-lived form the pattern
# targets; a lookalike that is too short is not a key.
test_no_violation_for_a_short_lookalike if {
	violations := hardcoded_credentials.violations with input as _res("aws_instance", {"user_data": "AKIASHORT"})
	count(violations) == 0
}

test_no_violation_for_ordinary_values if {
	violations := hardcoded_credentials.violations with input as _res("aws_instance", {"instance_type": "t3.micro", "ami": "ami-0123456789abcdef0"})
	count(violations) == 0
}

# The textbook version of this mistake is not in a resource at all. The rule
# walked `input.resource` only, so this was never scanned.
test_violation_for_a_provider_block if {
	violations := hardcoded_credentials.violations with input as {"provider": [{"aws": {
		"region": "eu-west-1",
		"access_key": "AKIAIOSFODNN7EXAMPLE",
		"__tf_file": "providers.tf",
	}}]}
	count(violations) == 1
	some v in violations
	v.resource_address == "provider.aws"
}

test_violation_for_a_variable_default if {
	violations := hardcoded_credentials.violations with input as {"variable": [{"gh_token": {
		"default": "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
		"__tf_file": "variables.tf",
	}}]}
	count(violations) == 1
	some v in violations
	v.resource_address == "variable.gh_token"
}

test_violation_for_a_local if {
	violations := hardcoded_credentials.violations with input as {"locals": [{"bootstrap": {
		"key": "AKIAIOSFODNN7EXAMPLE",
		"__tf_file": "locals.tf",
	}}]}
	count(violations) == 1
}

# Nine formats rather than one — the same set the workflow engine recognises.
test_violation_for_a_non_aws_credential_format if {
	violations := hardcoded_credentials.violations with input as _res("aws_ssm_parameter", {"value": "ghp_16C7e42F292c6912E7710c838347Ae178B4a"})
	count(violations) == 1
}

test_violation_for_a_data_source if {
	violations := hardcoded_credentials.violations with input as {"data": [{"external": {"creds": {
		"query": {"token": "AKIAIOSFODNN7EXAMPLE"},
		"__tf_file": "main.tf",
	}}}]}
	count(violations) == 1
	some v in violations
	v.resource_address == "external.creds"
}

# The finding must never carry the credential in its identity.
test_the_discriminator_is_not_the_secret if {
	violations := hardcoded_credentials.violations with input as _res("aws_instance", {"user_data": "AKIAIOSFODNN7EXAMPLE"})
	some v in violations
	not contains(v.discriminator, "AKIA")
	not contains(sprintf("%v", [v]), "AKIAIOSFODNN7EXAMPLE")
}
