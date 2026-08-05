# METADATA
# title: EKS cluster does not log audit events
# description: An EKS cluster does not send the Kubernetes audit log to CloudWatch, so there is no record of what any principal did through the API server. This is the log you need for the two questions that actually get asked after an incident — what did the compromised credential touch, and when did the change that broke production get applied — and neither CloudTrail nor pod logs answer them, because both sit on the wrong side of the API server. It cannot be enabled retroactively for the period you care about.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       eksctl create cluster --name prod --region eu-west-1
#     good: |
#       aws eks update-cluster-config --name prod \
#         --logging '{"clusterLogging":[{"types":["api","audit","authenticator"],"enabled":true}]}'
#     fix: |
#       Enable at least the `audit` and `authenticator` log types. They go to CloudWatch Logs and are billed by volume, so pair this with a retention policy on the log group rather than leaving it unbounded.
package greensecops.cloud_aws.reliability.eks_control_plane_logging_disabled

import rego.v1

violations contains violation if {
	some cluster in input.eks_clusters

	# Key on the cluster being present and its log set lacking audit, never on
	# the field being missing — that would be vacuously true for every document
	# in every other engine.
	is_array(cluster.enabled_log_types)
	not "audit" in cluster.enabled_log_types

	violation := {
		"rule": "eks_control_plane_logging_disabled",
		"severity": "medium",
		"category": "reliability",
		"resource_type": "aws_eks_cluster",
		"resource_id": cluster.name,
		"region": cluster.region,
		"message": sprintf("EKS cluster '%v' does not emit the audit log, so there is no record of what any principal did through its API server.", [cluster.name]),
	}
}
