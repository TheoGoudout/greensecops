# METADATA
# title: S3 bucket without versioning
# description: An aws_s3_bucket resource has no versioning block, so an accidental overwrite or delete of an object can't be recovered.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_s3_bucket" "data" {
#         bucket = "my-bucket"
#       }
#     good: |
#       resource "aws_s3_bucket" "data" {
#         bucket = "my-bucket"
#         versioning {
#           enabled = true
#         }
#       }
#     fix: |
#       Add a versioning block (or, on provider versions where bucket config is split, a separate aws_s3_bucket_versioning resource — not detected by this static-only check yet).
package greensecops.iac_terraform.reliability.s3_bucket_missing_versioning

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, bucket in res.aws_s3_bucket
	not bucket.versioning
	violation := {
		"rule": "s3_bucket_missing_versioning",
		"severity": "medium",
		"category": "reliability",
		"resource_address": sprintf("aws_s3_bucket.%v", [name]),
		"file_path": object.get(bucket, "__tf_file", ""),
		"line_start": object.get(bucket, "__start_line__", null),
		"line_end": object.get(bucket, "__end_line__", null),
		"message": sprintf(
			"S3 bucket '%v' has no versioning configured — accidental overwrites/deletes can't be recovered.",
			[name],
		),
	}
}
