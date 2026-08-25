# METADATA
# title: EKS API server is reachable from the internet
# description: An EKS cluster exposes its Kubernetes API endpoint publicly with no CIDR restriction, so the control plane's authentication is the only thing between the internet and the cluster. That is a much thinner margin than it sounds — the API server answers unauthenticated requests with version information, it is the target of every Kubernetes scanner on the internet, and a single leaked kubeconfig or over-broad IAM mapping turns reachability into cluster-admin. Private endpoints, or a public one scoped to your egress addresses, remove the whole class.
# custom:
#   severity: high
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws eks update-cluster-config --name prod \
#         --resources-vpc-config endpointPublicAccess=true,publicAccessCidrs=0.0.0.0/0
#     good: |
#       aws eks update-cluster-config --name prod \
#         --resources-vpc-config endpointPublicAccess=false,endpointPrivateAccess=true
#     fix: |
#       Turn the private endpoint on first and confirm your nodes and CI can still reach the API through it, then either disable public access or scope publicAccessCidrs to your VPN and CI egress ranges. Doing it the other way round locks you out.
package greensecops.cloud_aws.security.eks_public_endpoint

import rego.v1

violations contains violation if {
	some cluster in input.eks_clusters

	cluster.endpoint_public_access == true
	some cidr in cluster.public_access_cidrs
	cidr in {"0.0.0.0/0", "::/0"}

	violation := {
		"rule": "eks_public_endpoint",
		"severity": "high",
		"category": "security",
		"resource_type": "aws_eks_cluster",
		"resource_id": cluster.name,
		"region": cluster.region,
		"message": sprintf("EKS cluster '%v' exposes its API server to %v, so control-plane authentication is the only barrier from the internet.", [cluster.name, cidr]),
		# A cluster listing both `0.0.0.0/0` and `::/0` produced two violations
		# at one resource id, and the dedup key kept one of them arbitrarily.
		"discriminator": cidr,
	}
}
