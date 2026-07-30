# METADATA
# title: S3 bucket without versioning
# description: An aws_s3_bucket resource has neither an inline versioning block nor a companion aws_s3_bucket_versioning resource enabling versioning, so an accidental overwrite or delete of an object can't be recovered.
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
#       }
#
#       resource "aws_s3_bucket_versioning" "data" {
#         bucket = aws_s3_bucket.data.id
#         versioning_configuration {
#           status = "Enabled"
#         }
#       }
#     fix: |
#       Add a companion aws_s3_bucket_versioning resource with versioning_configuration.status = "Enabled" — the form the AWS provider has expected since v4. On an older provider, use an inline versioning block with enabled = true instead.
package greensecops.iac_terraform.reliability.s3_bucket_missing_versioning

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, bucket in res.aws_s3_bucket
	not bucket.versioning
	not _versioning_enabled_elsewhere(name, bucket)
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

# AWS provider v4 split the bucket sub-resources out of aws_s3_bucket: versioning
# now lives in its own aws_s3_bucket_versioning resource, which the inline check
# above cannot see. A companion resource targeting this bucket with status
# "Enabled" satisfies the rule exactly as the deprecated inline block does —
# without this, every config written against a modern provider is a false
# positive.
_versioning_enabled_elsewhere(bucket_name, bucket) if {
	some res in input.resource
	some _, versioning in res.aws_s3_bucket_versioning
	_targets_bucket(versioning, bucket_name, bucket)
	some config in _as_list(versioning.versioning_configuration)
	config.status == "Enabled"
}

# `bucket = aws_s3_bucket.<name>.id` reaches Rego as the literal interpolation
# string — hcl2 does not resolve references. Both `.id` and `.bucket` are valid
# ways to point at the bucket.
_targets_bucket(versioning, bucket_name, _) if {
	some attribute in {"id", "bucket"}
	versioning.bucket == sprintf("${aws_s3_bucket.%v.%v}", [bucket_name, attribute])
}

# ... or the same bucket name spelled out on both resources, reference-free.
_targets_bucket(versioning, _, bucket) if {
	versioning.bucket == bucket.bucket
}

# An HCL nested block parses to a single-element list; the equivalent .tf.json
# configuration carries a bare object. Normalise so both are handled.
_as_list(value) := value if is_array(value)

_as_list(value) := [value] if is_object(value)
