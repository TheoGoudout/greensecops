package greensecops.cloud_aws.reliability.cloudtrail_logging_disabled_test

import data.greensecops.cloud_aws.reliability.cloudtrail_logging_disabled
import rego.v1

# Mirrors services/cloud/aws_collector.collect_account_resources: each resource
# type is a list of flat objects. A field the collector could not read is
# omitted rather than defaulted, so "absent" has to be covered alongside
# "false".

_snapshot(resources) := {"cloudtrail_trails": resources}

test_violation_when_is_logging_is_false if {
	violations := cloudtrail_logging_disabled.violations with input as _snapshot([{"name": "org-audit", "region": "eu-west-1", "is_logging": false}])
	count(violations) == 1
	some v in violations
	v.resource_id == "org-audit"
	v.resource_type == "aws_cloudtrail_trail"
}

test_no_violation_when_is_logging_is_true if {
	violations := cloudtrail_logging_disabled.violations with input as _snapshot([{"name": "prod-audit", "region": "eu-west-1", "is_logging": true}])
	count(violations) == 0
}

test_violation_when_is_logging_is_absent if {
	violations := cloudtrail_logging_disabled.violations with input as _snapshot([{"name": "org-audit", "region": "eu-west-1"}])
	count(violations) == 1
}

test_no_violation_for_an_empty_account if {
	violations := cloudtrail_logging_disabled.violations with input as _snapshot([])
	count(violations) == 0
}

test_each_offending_resource_is_its_own_finding if {
	violations := cloudtrail_logging_disabled.violations with input as _snapshot([{"name": "org-audit", "region": "eu-west-1", "is_logging": false}, {"name": "team-audit", "region": "us-east-1", "is_logging": false}, {"name": "prod-audit", "region": "eu-west-1", "is_logging": true}])
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
