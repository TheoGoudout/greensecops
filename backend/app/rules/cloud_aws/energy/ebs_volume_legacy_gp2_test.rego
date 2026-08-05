package greensecops.cloud_aws.energy.ebs_volume_legacy_gp2_test

import data.greensecops.cloud_aws.energy.ebs_volume_legacy_gp2 as legacy_gp2
import rego.v1

_volume(volume_type, size_gb) := {"ebs_volumes": [{
	"id": "vol-0123",
	"region": "eu-west-1",
	"encrypted": true,
	"kms_key_id": "arn:...key/abc-123",
	"volume_type": volume_type,
	"size_gb": size_gb,
	"attached": true,
}]}

test_violation_for_a_gp2_volume if {
	violations := legacy_gp2.violations with input as _volume("gp2", 500)
	count(violations) == 1
	some v in violations
	v.resource_id == "vol-0123"
	v.category == "energy"
	v.severity == "low"
}

test_no_violation_for_a_gp3_volume if {
	violations := legacy_gp2.violations with input as _volume("gp3", 100)
	count(violations) == 0
}

# io1/io2 are provisioned-IOPS types chosen deliberately for latency, not
# leftovers from an older default.
test_no_violation_for_a_provisioned_iops_volume if {
	violations := legacy_gp2.violations with input as _volume("io2", 100)
	count(violations) == 0
}

test_the_message_reports_the_size if {
	violations := legacy_gp2.violations with input as _volume("gp2", 500)
	some v in violations
	contains(v.message, "500")
}

test_no_violation_for_an_empty_account if {
	violations := legacy_gp2.violations with input as {"ebs_volumes": []}
	count(violations) == 0
}

# Attachment is a separate rule's concern; an unattached gp2 volume is both.
test_an_unattached_gp2_volume_is_still_reported if {
	violations := legacy_gp2.violations with input as {"ebs_volumes": [{
		"id": "vol-0123",
		"region": "eu-west-1",
		"volume_type": "gp2",
		"size_gb": 500,
		"attached": false,
	}]}
	count(violations) == 1
}
