package greensecops.cloud_aws.reliability.rds_no_deletion_protection_test

import data.greensecops.cloud_aws.reliability.rds_no_deletion_protection as unprotected
import rego.v1

_db(protection) := {"rds_instances": [{
	"id": "prod",
	"region": "eu-west-1",
	"engine": "postgres",
	"backup_retention_days": 7,
	"multi_az": true,
	"deletion_protection": protection,
	"auto_minor_version_upgrade": true,
}]}

test_violation_when_protection_is_off if {
	violations := unprotected.violations with input as _db(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
}

test_no_violation_when_protection_is_on if {
	violations := unprotected.violations with input as _db(true)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := unprotected.violations with input as {"rds_instances": []}
	count(violations) == 0
}

# Backups are a separate concern — an instance with both problems is reported
# by both rules, and neither substitutes for the other.
test_backups_do_not_satisfy_this_rule if {
	violations := unprotected.violations with input as {"rds_instances": [{
		"id": "prod",
		"region": "eu-west-1",
		"backup_retention_days": 30,
		"deletion_protection": false,
	}]}
	count(violations) == 1
}
