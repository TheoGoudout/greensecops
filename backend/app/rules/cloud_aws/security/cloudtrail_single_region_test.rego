package greensecops.cloud_aws.security.cloudtrail_single_region_test

import data.greensecops.cloud_aws.security.cloudtrail_single_region as single_region
import rego.v1

_trail(name, multi_region) := _regional_trail(name, multi_region, "eu-west-1")

_regional_trail(name, multi_region, region) := {
	"name": name,
	"region": region,
	"is_logging": true,
	"is_multi_region": multi_region,
	"log_file_validation_enabled": true,
	"kms_key_id": null,
}

test_violation_when_the_only_trail_is_single_region if {
	violations := single_region.violations with input as {"cloudtrail_trails": [_trail("audit", false)]}
	count(violations) == 1
	some v in violations
	v.resource_id == "account"
	v.severity == "high"
}

test_no_violation_when_a_multi_region_trail_exists if {
	violations := single_region.violations with input as {"cloudtrail_trails": [_trail("audit", true)]}
	count(violations) == 0
}

# One multi-region trail covers the account, so single-region trails beside it
# are redundant rather than a gap.
test_no_violation_when_one_of_several_trails_is_multi_region if {
	violations := single_region.violations with input as {"cloudtrail_trails": [
		_trail("local", false),
		_trail("audit", true),
	]}
	count(violations) == 0
}

# An empty list also means "no permission to read trails". cloudtrail_absent
# covers a genuinely untrailed account; this rule must not double-report it or
# fire on an under-permissioned role.
test_no_violation_for_an_account_with_no_trails if {
	violations := single_region.violations with input as {"cloudtrail_trails": []}
	count(violations) == 0
}

# "No trail in this account is multi-region" is one fact about the account.
# Reporting it once per trail produced N findings for one gap, each naming a
# different trail as though each were separately at fault.
test_one_finding_however_many_narrow_trails_there_are if {
	violations := single_region.violations with input as {"cloudtrail_trails": [
		_regional_trail("eu", false, "eu-west-1"),
		_regional_trail("us", false, "us-east-1"),
	]}
	count(violations) == 1
}

test_the_finding_lists_the_regions_that_are_covered if {
	violations := single_region.violations with input as {"cloudtrail_trails": [
		_regional_trail("eu", false, "eu-west-1"),
		_regional_trail("us", false, "us-east-1"),
	]}
	some v in violations
	v.context == "eu-west-1, us-east-1"
}
