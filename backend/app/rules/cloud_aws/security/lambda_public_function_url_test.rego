package greensecops.cloud_aws.security.lambda_public_function_url_test

import data.greensecops.cloud_aws.security.lambda_public_function_url
import rego.v1

# Mirrors services/cloud/aws_collector.collect_account_resources: each resource
# type is a list of flat objects. A field the collector could not read is
# omitted rather than defaulted, so "absent" has to be covered alongside
# "false".

_snapshot(resources) := {"lambda_functions": resources}

test_violation_when_public_url_is_true if {
	violations := lambda_public_function_url.violations with input as _snapshot([{"name": "api", "region": "eu-west-1", "runtime": "python3.13", "public_url": true}])
	count(violations) == 1
	some v in violations
	v.resource_id == "api"
	v.resource_type == "aws_lambda_function"
}

test_no_violation_when_public_url_is_false if {
	violations := lambda_public_function_url.violations with input as _snapshot([{"name": "worker", "region": "eu-west-1", "runtime": "python3.13", "public_url": false}])
	count(violations) == 0
}

test_no_violation_when_public_url_is_absent if {
	violations := lambda_public_function_url.violations with input as _snapshot([{"name": "api", "region": "eu-west-1", "runtime": "python3.13"}])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := lambda_public_function_url.violations with input as _snapshot([])
	count(violations) == 0
}

test_each_offending_resource_is_its_own_finding if {
	violations := lambda_public_function_url.violations with input as _snapshot([{"name": "api", "region": "eu-west-1", "runtime": "python3.13", "public_url": true}, {"name": "webhook", "region": "eu-west-1", "runtime": "python3.13", "public_url": true}, {"name": "worker", "region": "eu-west-1", "runtime": "python3.13", "public_url": false}])
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
