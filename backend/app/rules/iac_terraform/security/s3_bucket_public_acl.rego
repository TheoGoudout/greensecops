# METADATA
# title: S3 bucket with a public ACL
# description: An aws_s3_bucket resource sets acl to "public-read" or "public-read-write", making every object in the bucket readable (or writable) by anyone on the internet by default.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_s3_bucket" "data" {
#         bucket = "my-bucket"
#         acl    = "public-read"
#       }
#     good: |
#       resource "aws_s3_bucket" "data" {
#         bucket = "my-bucket"
#         acl    = "private"
#       }
#     fix: |
#       Set acl to "private" and use aws_s3_bucket_policy for any deliberate, narrowly-scoped public access instead of a bucket-wide ACL.
package greensecops.iac_terraform.security.s3_bucket_public_acl

import rego.v1

_public_acls := {"public-read", "public-read-write"}

# `aws_s3_bucket.acl` was removed from the AWS provider in v4 — every current
# configuration expresses this through `aws_s3_bucket_acl` instead, which this
# rule did not read. The inline argument is kept for the modules still on v3.
violations contains violation if {
	some res in input.resource
	some name, attrs in res.aws_s3_bucket_acl
	acl := attrs.acl
	acl in _public_acls

	violation := {
		"rule": "s3_bucket_public_acl",
		"severity": "high",
		"category": "security",
		"resource_address": sprintf("aws_s3_bucket_acl.%v", [name]),
		"file_path": object.get(attrs, "__tf_file", ""),
		"line_start": object.get(attrs, "__start_line__", null),
		"line_end": object.get(attrs, "__end_line__", null),
		"message": sprintf("S3 bucket ACL '%v' is %v. Every object the bucket holds is readable by anyone on the internet.", [name, acl]),
		"context": acl,
	}
}

violations contains violation if {
	some res in input.resource
	some name, bucket in res.aws_s3_bucket
	acl := bucket.acl
	acl in _public_acls
	violation := {
		"rule": "s3_bucket_public_acl",
		"severity": "high",
		"category": "security",
		"resource_address": sprintf("aws_s3_bucket.%v", [name]),
		"file_path": object.get(bucket, "__tf_file", ""),
		"line_start": object.get(bucket, "__start_line__", null),
		"line_end": object.get(bucket, "__end_line__", null),
		"message": sprintf("S3 bucket '%v' has a public ACL (%v). Every object is readable by anyone on the internet.", [name, acl]),
	}
}
