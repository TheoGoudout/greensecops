package greensecops.cloud_aws.maintainability.rds_auto_minor_upgrade_disabled_test

import data.greensecops.cloud_aws.maintainability.rds_auto_minor_upgrade_disabled as no_upgrades
import rego.v1

_db(auto_upgrade) := {"rds_instances": [{
	"id": "prod",
	"region": "eu-west-1",
	"engine": "postgres",
	"backup_retention_days": 7,
	"multi_az": true,
	"deletion_protection": true,
	"auto_minor_version_upgrade": auto_upgrade,
}]}

test_violation_when_auto_upgrade_is_off if {
	violations := no_upgrades.violations with input as _db(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
	v.category == "maintainability"
}

test_no_violation_when_auto_upgrade_is_on if {
	violations := no_upgrades.violations with input as _db(true)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := no_upgrades.violations with input as {"rds_instances": []}
	count(violations) == 0
}

test_each_instance_is_its_own_finding if {
	violations := no_upgrades.violations with input as {"rds_instances": [
		{"id": "prod", "region": "eu-west-1", "auto_minor_version_upgrade": false},
		{"id": "analytics", "region": "eu-west-1", "auto_minor_version_upgrade": false},
		{"id": "staging", "region": "eu-west-1", "auto_minor_version_upgrade": true},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
