# METADATA
# title: CloudTrail records only one region
# description: Every CloudTrail trail in the account is single-region, so API activity anywhere else is not recorded at all. This is the gap an attacker who has read your trail configuration will use — spin resources up in a region nobody watches, and there is no log to find them in afterwards, not a log you have to search harder. Multi-region is a single flag and costs nothing extra for the management events that make up almost all of the volume.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws cloudtrail create-trail --name audit --s3-bucket-name audit-logs
#     good: |
#       aws cloudtrail create-trail --name audit --s3-bucket-name audit-logs \
#         --is-multi-region-trail
#     fix: |
#       Run `aws cloudtrail update-trail --name <trail> --is-multi-region-trail`. One multi-region trail replaces a per-region fleet, and management events for the first copy of a trail are not billed.
package greensecops.cloud_aws.security.cloudtrail_single_region

import rego.v1

_has_multi_region_trail if {
	some trail in input.cloudtrail_trails
	trail.is_multi_region == true
}

# "No trail in this account is multi-region" is one fact about the account, not
# one fact per trail. Emitting it per trail produced N findings for a single
# gap, each naming a different trail as though each were separately at fault.
_covered_regions := {trail.region |
	some trail in input.cloudtrail_trails
	is_string(trail.region)
}

violations contains violation if {
	# Keyed on a trail being present and narrow, never on the list being empty
	# — an empty list also means "no permission to read trails", and
	# cloudtrail_absent already covers a genuinely untrailed account.
	count(input.cloudtrail_trails) > 0
	not _has_multi_region_trail

	regions := concat(", ", sort(_covered_regions))
	violation := {
		"rule": "cloudtrail_single_region",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_cloudtrail",
		"resource_id": "account",
		"message": sprintf("No trail in this account is multi-region. The %v trail(s) that exist record only %v, so API activity in every other region goes unrecorded — including a region chosen precisely because nothing is watching it.", [count(input.cloudtrail_trails), regions]),
		"context": regions,
		"discriminator": "account",
	}
}
