package greensecops.cloud_aws.reliability.cloudtrail_absent_test

import data.greensecops.cloud_aws.reliability.cloudtrail_absent
import rego.v1

test_violation_when_the_account_has_no_trails if {
	violations := cloudtrail_absent.violations with input as {"cloudtrail_trails": []}
	count(violations) == 1
	some v in violations
	v.severity == "high"
	v.resource_id == "account"
}

# collect_account_resources always emits all eight resource keys, so an absent
# one means this is not a cloud snapshot. Firing on a missing key would make
# the rule fire on every workflow, Dockerfile and Terraform document too — the
# cross-domain check in scripts/validate_examples.py caught exactly that.
test_no_violation_when_the_key_is_absent if {
	violations := cloudtrail_absent.violations with input as {"s3_buckets": []}
	count(violations) == 0
}

test_no_violation_on_a_document_from_another_engine if {
	violations := cloudtrail_absent.violations with input as {"jobs": {"build": {"steps": []}}}
	count(violations) == 0
}

test_no_violation_when_a_trail_exists if {
	violations := cloudtrail_absent.violations with input as {"cloudtrail_trails": [{
		"name": "org-audit",
		"region": "eu-west-1",
		"is_logging": true,
	}]}
	count(violations) == 0
}

# A trail that exists but has stopped is cloudtrail_logging_disabled's finding,
# not this one — the two must not both fire on the same account.
test_no_violation_when_a_trail_exists_but_is_stopped if {
	violations := cloudtrail_absent.violations with input as {"cloudtrail_trails": [{
		"name": "org-audit",
		"region": "eu-west-1",
		"is_logging": false,
	}]}
	count(violations) == 0
}

test_one_finding_per_account_not_per_region if {
	violations := cloudtrail_absent.violations with input as {"cloudtrail_trails": [], "security_groups": []}
	count(violations) == 1
}
