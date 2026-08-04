package greensecops.cloud_aws.security.ebs_volume_unencrypted_test

import data.greensecops.cloud_aws.security.ebs_volume_unencrypted
import rego.v1

# Mirrors services/cloud/aws_collector.collect_account_resources: each resource
# type is a list of flat objects. A field the collector could not read is
# omitted rather than defaulted, so "absent" has to be covered alongside
# "false".

_snapshot(resources) := {"ebs_volumes": resources}

test_violation_when_encrypted_is_false if {
	violations := ebs_volume_unencrypted.violations with input as _snapshot([{"id": "vol-0123", "region": "eu-west-1", "encrypted": false, "attached": true}])
	count(violations) == 1
	some v in violations
	v.resource_id == "vol-0123"
	v.resource_type == "aws_ebs_volume"
}

test_no_violation_when_encrypted_is_true if {
	violations := ebs_volume_unencrypted.violations with input as _snapshot([{"id": "vol-0789", "region": "eu-west-1", "encrypted": true, "attached": true}])
	count(violations) == 0
}

test_violation_when_encrypted_is_absent if {
	violations := ebs_volume_unencrypted.violations with input as _snapshot([{"id": "vol-0123", "region": "eu-west-1", "attached": true}])
	count(violations) == 1
}

test_no_violation_for_an_empty_account if {
	violations := ebs_volume_unencrypted.violations with input as _snapshot([])
	count(violations) == 0
}

test_each_offending_resource_is_its_own_finding if {
	violations := ebs_volume_unencrypted.violations with input as _snapshot([{"id": "vol-0123", "region": "eu-west-1", "encrypted": false, "attached": true}, {"id": "vol-0456", "region": "eu-west-1", "encrypted": false, "attached": true}, {"id": "vol-0789", "region": "eu-west-1", "encrypted": true, "attached": true}])
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
