package greensecops.cloud_aws.security.s3_bucket_unencrypted_test

import data.greensecops.cloud_aws.security.s3_bucket_unencrypted
import rego.v1

# Mirrors services/cloud/aws_collector.collect_account_resources: each resource
# type is a list of flat objects. A field the collector could not read is
# omitted rather than defaulted, so "absent" has to be covered alongside
# "false".

_snapshot(resources) := {"s3_buckets": resources}

test_violation_when_encrypted_is_false if {
	violations := s3_bucket_unencrypted.violations with input as _snapshot([{"name": "assets", "encrypted": false, "versioning_enabled": true}])
	count(violations) == 1
	some v in violations
	v.resource_id == "assets"
	v.resource_type == "aws_s3_bucket"
}

test_no_violation_when_encrypted_is_true if {
	violations := s3_bucket_unencrypted.violations with input as _snapshot([{"name": "backups", "encrypted": true, "versioning_enabled": true}])
	count(violations) == 0
}

test_violation_when_encrypted_is_absent if {
	violations := s3_bucket_unencrypted.violations with input as _snapshot([{"name": "assets", "versioning_enabled": true}])
	count(violations) == 1
}

test_no_violation_for_an_empty_account if {
	violations := s3_bucket_unencrypted.violations with input as _snapshot([])
	count(violations) == 0
}

test_each_offending_resource_is_its_own_finding if {
	violations := s3_bucket_unencrypted.violations with input as _snapshot([{"name": "assets", "encrypted": false, "versioning_enabled": true}, {"name": "reports", "encrypted": false, "versioning_enabled": true}, {"name": "backups", "encrypted": true, "versioning_enabled": true}])
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
