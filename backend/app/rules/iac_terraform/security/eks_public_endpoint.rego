# METADATA
# title: EKS cluster API endpoint is open to the internet
# description: An aws_eks_cluster enables public endpoint access without narrowing public_access_cidrs, so the Kubernetes API server is reachable from anywhere. The API server is the control plane for everything in the cluster, and leaving it globally reachable means any authentication weakness, leaked kubeconfig or token is directly exploitable from the internet rather than needing network access first.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_eks_cluster" "main" {
#         name = "main"
#         vpc_config {
#           endpoint_public_access = true
#           public_access_cidrs    = ["0.0.0.0/0"]
#         }
#       }
#     good: |
#       resource "aws_eks_cluster" "main" {
#         name = "main"
#         vpc_config {
#           endpoint_public_access  = true
#           endpoint_private_access = true
#           public_access_cidrs     = ["203.0.113.0/24"]
#         }
#       }
#     fix: |
#       Narrow public_access_cidrs to the ranges that administer the cluster, and enable endpoint_private_access so in-VPC traffic never leaves the network. Turning public access off entirely is better still where CI reaches the cluster from inside the VPC.
package greensecops.iac_terraform.security.eks_public_endpoint

import rego.v1

# A nested HCL block arrives as a single-element list, while the same block in
# a .tf.json file is a bare object. Both spellings have to be read.
_vpc_configs(cluster) := configs if {
	is_array(cluster.vpc_config)
	configs := cluster.vpc_config
}

_vpc_configs(cluster) := [cluster.vpc_config] if {
	is_object(cluster.vpc_config)
}

_open_cidr := {"0.0.0.0/0", "::/0"}

violations contains violation if {
	some res in input.resource
	some name, cluster in res.aws_eks_cluster
	some config in _vpc_configs(cluster)

	config.endpoint_public_access == true
	some cidr in object.get(config, "public_access_cidrs", ["0.0.0.0/0"])
	cidr in _open_cidr

	violation := {
		"rule": "eks_public_endpoint",
		"severity": "high",
		"category": "security",
		"resource_address": sprintf("aws_eks_cluster.%v", [name]),
		"file_path": object.get(cluster, "__tf_file", ""),
		"line_start": object.get(cluster, "__start_line__", null),
		"line_end": object.get(cluster, "__end_line__", null),
		"message": sprintf("EKS cluster '%v' exposes its Kubernetes API endpoint to %v, so the control plane is reachable from the internet.", [name, cidr]),
	}
}
