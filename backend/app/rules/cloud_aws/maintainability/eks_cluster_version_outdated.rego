# METADATA
# title: EKS cluster runs an unsupported Kubernetes version
# description: An EKS cluster runs a Kubernetes version below 1.32, the floor of AWS's standard support window at the time of writing. AWS keeps such a cluster running on extended support at roughly six times the control-plane cost, and eventually upgrades it for you on a schedule you did not pick. Upgrades are also strictly sequential — one minor version at a time, each with its own deprecated-API check — so falling behind compounds, because the work to catch up grows faster than the time spent behind, which is what turns a deferred upgrade into a project.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       # aws eks describe-cluster --name prod --query cluster.version
#       # "1.27"
#     good: |
#       aws eks update-cluster-version --name prod --kubernetes-version 1.31
#     fix: |
#       Upgrade one minor version at a time, checking the deprecated API report in the EKS console before each step. Upgrade the control plane first, then the node groups and the add-ons — a control plane may run at most two minor versions ahead of its nodes.
package greensecops.cloud_aws.maintainability.eks_cluster_version_outdated

import rego.v1

# The oldest version still in AWS's standard support window. Bump this as the
# window moves — the same maintenance the lambda_deprecated_runtime list needs.
# The floor of EKS standard support. This is a moving number — AWS retires a
# minor version roughly every three months — so it is stated once here rather
# than spread through the rule, and the METADATA description names it so a
# reader can tell at a glance whether the catalog has fallen behind.
_minimum_supported_minor := 32

_minor_version(version) := minor if {
	parts := split(version, ".")
	count(parts) >= 2
	minor := to_number(parts[1])
}

violations contains violation if {
	some cluster in input.eks_clusters

	minor := _minor_version(cluster.version)
	minor < _minimum_supported_minor

	violation := {
		"rule": "eks_cluster_version_outdated",
		"severity": "medium",
		"category": "maintainability",
		"resource_type": "aws_eks_cluster",
		"resource_id": cluster.name,
		"region": cluster.region,
		"message": sprintf("EKS cluster '%v' runs Kubernetes %v, past standard support (1.%v) — it is billed at the extended-support rate and each deferred minor version makes the catch-up larger.", [cluster.name, cluster.version, _minimum_supported_minor]),
	}
}
