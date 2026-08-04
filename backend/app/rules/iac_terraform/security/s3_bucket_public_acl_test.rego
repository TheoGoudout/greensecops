package greensecops.iac_terraform.security.s3_bucket_public_acl_test

import data.greensecops.iac_terraform.security.s3_bucket_public_acl
import rego.v1

# `resource` is a list of single-key objects nested {type: {name: attrs}}, and
# source metadata rides along under double-underscore keys.

_bucket(attrs) := {"resource": [{"aws_s3_bucket": {"data": object.union(
	{"bucket": "my-bucket", "__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 8},
	attrs,
)}}]}

test_violation_for_public_read if {
	violations := s3_bucket_public_acl.violations with input as _bucket({"acl": "public-read"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_s3_bucket.data"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_violation_for_public_read_write if {
	violations := s3_bucket_public_acl.violations with input as _bucket({"acl": "public-read-write"})
	count(violations) == 1
}

test_no_violation_for_a_private_acl if {
	violations := s3_bucket_public_acl.violations with input as _bucket({"acl": "private"})
	count(violations) == 0
}

# authenticated-read is every AWS account, which is broad but not public.
test_no_violation_for_authenticated_read if {
	violations := s3_bucket_public_acl.violations with input as _bucket({"acl": "authenticated-read"})
	count(violations) == 0
}

test_no_violation_when_no_acl_is_set if {
	violations := s3_bucket_public_acl.violations with input as _bucket({})
	count(violations) == 0
}

test_each_public_bucket_is_its_own_finding if {
	violations := s3_bucket_public_acl.violations with input as {"resource": [
		{"aws_s3_bucket": {"a": {"bucket": "a", "acl": "public-read"}}},
		{"aws_s3_bucket": {"b": {"bucket": "b", "acl": "public-read-write"}}},
		{"aws_s3_bucket": {"c": {"bucket": "c", "acl": "private"}}},
	]}
	count(violations) == 2
	{v.resource_address | some v in violations} == {"aws_s3_bucket.a", "aws_s3_bucket.b"}
}
