package greensecops.cloud_aws.reliability.rds_no_backup_retention_test

import data.greensecops.cloud_aws.reliability.rds_no_backup_retention as no_backups
import rego.v1

_db(retention) := {"rds_instances": [{
	"id": "prod",
	"region": "eu-west-1",
	"engine": "postgres",
	"backup_retention_days": retention,
	"multi_az": true,
	"deletion_protection": true,
	"auto_minor_version_upgrade": true,
}]}

test_violation_when_retention_is_zero if {
	violations := no_backups.violations with input as _db(0)
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
	v.severity == "high"
}

test_no_violation_for_a_week_of_retention if {
	violations := no_backups.violations with input as _db(7)
	count(violations) == 0
}

# One day is short but is not "off" — point-in-time recovery still works.
test_no_violation_for_a_single_day if {
	violations := no_backups.violations with input as _db(1)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := no_backups.violations with input as {"rds_instances": []}
	count(violations) == 0
}

test_each_instance_is_its_own_finding if {
	violations := no_backups.violations with input as {"rds_instances": [
		{"id": "prod", "region": "eu-west-1", "backup_retention_days": 0},
		{"id": "analytics", "region": "eu-west-1", "backup_retention_days": 0},
		{"id": "staging", "region": "eu-west-1", "backup_retention_days": 7},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
