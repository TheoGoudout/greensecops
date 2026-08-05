package greensecops.cloud_aws.security.eks_secrets_not_encrypted_test

import data.greensecops.cloud_aws.security.eks_secrets_not_encrypted as unencrypted_secrets
import rego.v1

_cluster(secrets_encrypted) := {"eks_clusters": [{
	"name": "prod",
	"region": "eu-west-1",
	"version": "1.31",
	"endpoint_public_access": false,
	"endpoint_private_access": true,
	"public_access_cidrs": [],
	"enabled_log_types": ["api", "audit"],
	"secrets_encrypted": secrets_encrypted,
}]}

test_violation_when_envelope_encryption_is_absent if {
	violations := unencrypted_secrets.violations with input as _cluster(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
	v.severity == "medium"
}

test_no_violation_when_envelope_encryption_is_configured if {
	violations := unencrypted_secrets.violations with input as _cluster(true)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := unencrypted_secrets.violations with input as {"eks_clusters": []}
	count(violations) == 0
}

test_each_cluster_is_its_own_finding if {
	violations := unencrypted_secrets.violations with input as {"eks_clusters": [
		{"name": "prod", "region": "eu-west-1", "secrets_encrypted": false},
		{"name": "staging", "region": "us-east-1", "secrets_encrypted": false},
		{"name": "dev", "region": "us-east-1", "secrets_encrypted": true},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
