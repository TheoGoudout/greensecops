package greensecops.cloud_aws.security.rds_publicly_accessible_test

import data.greensecops.cloud_aws.security.rds_publicly_accessible
import rego.v1

# Mirrors services/cloud/aws_collector.collect_account_resources: each resource
# type is a list of flat objects. A field the collector could not read is
# omitted rather than defaulted, so "absent" has to be covered alongside
# "false".

_snapshot(resources) := {"rds_instances": resources}

test_violation_when_publicly_accessible_is_true if {
	violations := rds_publicly_accessible.violations with input as _snapshot([{"id": "app-db", "region": "eu-west-1", "publicly_accessible": true, "storage_encrypted": true}])
	count(violations) == 1
	some v in violations
	v.resource_id == "app-db"
	v.resource_type == "aws_db_instance"
}

test_no_violation_when_publicly_accessible_is_false if {
	violations := rds_publicly_accessible.violations with input as _snapshot([{"id": "internal-db", "region": "eu-west-1", "publicly_accessible": false, "storage_encrypted": true}])
	count(violations) == 0
}

test_no_violation_when_publicly_accessible_is_absent if {
	violations := rds_publicly_accessible.violations with input as _snapshot([{"id": "app-db", "region": "eu-west-1", "storage_encrypted": true}])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := rds_publicly_accessible.violations with input as _snapshot([])
	count(violations) == 0
}

test_each_offending_resource_is_its_own_finding if {
	violations := rds_publicly_accessible.violations with input as _snapshot([{"id": "app-db", "region": "eu-west-1", "publicly_accessible": true, "storage_encrypted": true}, {"id": "reports-db", "region": "eu-west-1", "publicly_accessible": true, "storage_encrypted": true}, {"id": "internal-db", "region": "eu-west-1", "publicly_accessible": false, "storage_encrypted": true}])
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
