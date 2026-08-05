package greensecops.iac_terraform.security.eks_public_endpoint_test

import data.greensecops.iac_terraform.security.eks_public_endpoint
import rego.v1

# A nested HCL block becomes a single-element list; the same block written in a
# .tf.json file stays a bare object. Both spellings have to be read.

_cluster(vpc_config) := {"resource": [{"aws_eks_cluster": {"main": {
	"name": "main",
	"vpc_config": vpc_config,
	"__tf_file": "eks.tf",
	"__start_line__": 3,
	"__end_line__": 12,
}}}]}

test_violation_for_public_access_from_anywhere if {
	violations := eks_public_endpoint.violations with input as _cluster([{
		"endpoint_public_access": true,
		"public_access_cidrs": ["0.0.0.0/0"],
	}])
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_eks_cluster.main"
	v.file_path == "eks.tf"
}

# public_access_cidrs defaults to 0.0.0.0/0 when omitted, so enabling public
# access alone is the same exposure.
test_violation_when_cidrs_are_omitted if {
	violations := eks_public_endpoint.violations with input as _cluster([{"endpoint_public_access": true}])
	count(violations) == 1
}

test_violation_for_the_json_style_object_form if {
	violations := eks_public_endpoint.violations with input as _cluster({
		"endpoint_public_access": true,
		"public_access_cidrs": ["0.0.0.0/0"],
	})
	count(violations) == 1
}

test_violation_for_an_open_ipv6_cidr if {
	violations := eks_public_endpoint.violations with input as _cluster([{
		"endpoint_public_access": true,
		"public_access_cidrs": ["::/0"],
	}])
	count(violations) == 1
}

test_no_violation_for_narrowed_cidrs if {
	violations := eks_public_endpoint.violations with input as _cluster([{
		"endpoint_public_access": true,
		"endpoint_private_access": true,
		"public_access_cidrs": ["203.0.113.0/24"],
	}])
	count(violations) == 0
}

test_no_violation_when_public_access_is_disabled if {
	violations := eks_public_endpoint.violations with input as _cluster([{
		"endpoint_public_access": false,
		"endpoint_private_access": true,
	}])
	count(violations) == 0
}

# An open CIDR is only a finding when public access is actually on.
test_no_violation_for_an_open_cidr_with_public_access_off if {
	violations := eks_public_endpoint.violations with input as _cluster([{
		"endpoint_public_access": false,
		"public_access_cidrs": ["0.0.0.0/0"],
	}])
	count(violations) == 0
}

test_no_violation_when_vpc_config_is_absent if {
	violations := eks_public_endpoint.violations with input as {"resource": [{"aws_eks_cluster": {"main": {"name": "main"}}}]}
	count(violations) == 0
}
