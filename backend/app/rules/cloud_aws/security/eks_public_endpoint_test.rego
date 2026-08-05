package greensecops.cloud_aws.security.eks_public_endpoint_test

import data.greensecops.cloud_aws.security.eks_public_endpoint as public_endpoint
import rego.v1

_cluster(public_access, cidrs) := {"eks_clusters": [{
	"name": "prod",
	"region": "eu-west-1",
	"version": "1.31",
	"endpoint_public_access": public_access,
	"endpoint_private_access": true,
	"public_access_cidrs": cidrs,
	"enabled_log_types": ["api", "audit"],
	"secrets_encrypted": true,
}]}

test_violation_for_an_unrestricted_public_endpoint if {
	violations := public_endpoint.violations with input as _cluster(true, ["0.0.0.0/0"])
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
	v.severity == "high"
}

# A public endpoint scoped to known egress ranges is the supported middle
# ground, not a finding.
test_no_violation_when_public_access_is_scoped if {
	violations := public_endpoint.violations with input as _cluster(true, ["203.0.113.0/24"])
	count(violations) == 0
}

test_no_violation_when_the_endpoint_is_private if {
	violations := public_endpoint.violations with input as _cluster(false, [])
	count(violations) == 0
}

# publicAccessCidrs is retained while public access is off; the flag decides.
test_no_violation_when_public_access_is_off_despite_an_open_cidr if {
	violations := public_endpoint.violations with input as _cluster(false, ["0.0.0.0/0"])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := public_endpoint.violations with input as {"eks_clusters": []}
	count(violations) == 0
}

test_each_exposed_cluster_is_its_own_finding if {
	violations := public_endpoint.violations with input as {"eks_clusters": [
		{"name": "prod", "region": "eu-west-1", "endpoint_public_access": true, "public_access_cidrs": ["0.0.0.0/0"]},
		{"name": "staging", "region": "eu-west-1", "endpoint_public_access": true, "public_access_cidrs": ["0.0.0.0/0"]},
		{"name": "dev", "region": "eu-west-1", "endpoint_public_access": true, "public_access_cidrs": ["10.0.0.0/8"]},
	]}
	count(violations) == 2
}
