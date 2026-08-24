# METADATA
# title: S3 bucket has no full public access block
# description: A bucket has no aws_s3_bucket_public_access_block covering it, or has one with a setting left false. The block is the account-level backstop that makes a public ACL or bucket policy fail closed regardless of what anything else sets — so with it in place, the s3_bucket_public_acl finding cannot actually expose data, and without it a single later policy edit can. All four settings matter, because each disables a different route to public.
# custom:
#   severity: high
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
#       resource "aws_s3_bucket_public_access_block" "data" {
#         bucket                  = aws_s3_bucket.data.id
#         block_public_acls       = true
#         block_public_policy     = true
#         ignore_public_acls      = true
#         restrict_public_buckets = true
#       }
#     fix: |
#       Add an aws_s3_bucket_public_access_block for the bucket with all four settings true. For a bucket that genuinely serves public content, front it with CloudFront and an origin access identity rather than making the bucket itself public.
package greensecops.iac_terraform.security.s3_public_access_block_disabled

import rego.v1

_required_settings := {
	"block_public_acls",
	"block_public_policy",
	"ignore_public_acls",
	"restrict_public_buckets",
}

# A companion resource references its bucket by resource name
# (aws_s3_bucket.data.id) or by the literal bucket name, exactly as
# s3_bucket_missing_versioning has to handle.
_references(block, bucket_name, _) if {
	contains(block.bucket, sprintf("aws_s3_bucket.%v.", [bucket_name]))
}

_references(block, _, bucket_attrs) if {
	block.bucket == bucket_attrs.bucket
}

_blocks_for(bucket_name, bucket_attrs) := [attrs |
	some res in input.resource
	some _, attrs in res.aws_s3_bucket_public_access_block
	_references(attrs, bucket_name, bucket_attrs)
]

_enabled(value) if value == true

# hcl2 does not evaluate expressions, so `block_public_acls = var.block_public`
# arrives as the string "${var.block_public}". The value is unknowable here,
# but a module that takes the setting as an input has made the decision
# deliberately — treating a reference as `false` would report every
# parameterised module, which is most real Terraform.
_enabled(value) if {
	is_string(value)
	trim_space(value) != ""
}

_fully_blocked(attrs) if {
	every setting in _required_settings {
		_enabled(attrs[setting])
	}
}

violations contains violation if {
	some res in input.resource
	some name, bucket in res.aws_s3_bucket

	blocks := _blocks_for(name, bucket)
	count([attrs | some attrs in blocks; _fully_blocked(attrs)]) == 0

	violation := {
		"rule": "s3_public_access_block_disabled",
		"severity": "high",
		"category": "security",
		"resource_address": sprintf("aws_s3_bucket.%v", [name]),
		"file_path": object.get(bucket, "__tf_file", ""),
		"line_start": object.get(bucket, "__start_line__", null),
		"line_end": object.get(bucket, "__end_line__", null),
		"message": sprintf("Bucket '%v' has no public access block with all four settings enabled, so a later ACL or policy change can make it public.", [name]),
	}
}
