package greensecops.cloud_aws.reliability.rds_not_multi_az_test

import data.greensecops.cloud_aws.reliability.rds_not_multi_az as single_az
import rego.v1

_db(multi_az) := {"rds_instances": [{
	"id": "prod",
	"region": "eu-west-1",
	"engine": "postgres",
	"backup_retention_days": 7,
	"multi_az": multi_az,
	"deletion_protection": true,
	"auto_minor_version_upgrade": true,
}]}

test_violation_for_a_single_az_instance if {
	violations := single_az.violations with input as _db(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
	v.severity == "medium"
}

test_no_violation_for_a_multi_az_instance if {
	violations := single_az.violations with input as _db(true)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := single_az.violations with input as {"rds_instances": []}
	count(violations) == 0
}

test_each_instance_is_its_own_finding if {
	violations := single_az.violations with input as {"rds_instances": [
		{"id": "prod", "region": "eu-west-1", "multi_az": false},
		{"id": "analytics", "region": "us-east-1", "multi_az": false},
		{"id": "staging", "region": "us-east-1", "multi_az": true},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
