# METADATA
# title: Resource missing tags
# description: A resource of a type that supports the tags argument has none set, making cost attribution and ownership harder to track.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_instance" "app" {
#         ami           = "ami-123"
#         instance_type = "t3.micro"
#       }
#     good: |
#       resource "aws_instance" "app" {
#         ami           = "ami-123"
#         instance_type = "t3.micro"
#         tags = {
#           Team = "platform"
#         }
#       }
#     fix: |
#       Add a tags map (or default_tags on the provider block, which this static check does not currently account for).
package greensecops.iac_terraform.maintainability.resource_missing_tags

import rego.v1

# Curated to resource types known to support the `tags` argument, matching
# the MVP resource set — avoids false positives on types that don't.
_taggable_types := {
	"aws_s3_bucket", "aws_instance", "aws_security_group", "aws_vpc",
	"aws_subnet", "aws_db_instance", "aws_lambda_function", "aws_ebs_volume",
}

violations contains violation if {
	some res in input.resource
	some res_type, named in res
	res_type in _taggable_types
	some name, attrs in named
	not attrs.tags
	violation := {
		"rule": "resource_missing_tags",
		"severity": "low",
		"category": "maintainability",
		"resource_address": sprintf("%v.%v", [res_type, name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"message": sprintf("Resource '%v.%v' has no tags — harder to attribute cost/ownership.", [res_type, name]),
	}
}
