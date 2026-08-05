# METADATA
# title: EKS cluster does not encrypt secrets with KMS
# description: An EKS cluster has no envelope-encryption configuration, so Kubernetes Secrets are stored in etcd with only the disk-level encryption AWS applies to the managed control plane. Anything that can read etcd, or a control-plane backup, reads every Secret in the cluster in plaintext. Envelope encryption with a KMS key means those reads produce ciphertext instead, and the decrypt becomes a key-policy decision you can audit and revoke.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       eksctl create cluster --name prod --region eu-west-1
#     good: |
#       aws eks associate-encryption-config --cluster-name prod \
#         --encryption-config '[{"resources":["secrets"],"provider":{"keyArn":"arn:aws:kms:eu-west-1:123456789012:key/abc-123"}}]'
#     fix: |
#       Associate an encryption config with a customer-managed key. It can be added to a running cluster, but it applies only to Secrets written afterwards — rewrite the existing ones (a no-op annotation change is enough) so the whole set is covered.
package greensecops.cloud_aws.security.eks_secrets_not_encrypted

import rego.v1

violations contains violation if {
	some cluster in input.eks_clusters

	cluster.secrets_encrypted == false

	violation := {
		"rule": "eks_secrets_not_encrypted",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_eks_cluster",
		"resource_id": cluster.name,
		"region": cluster.region,
		"message": sprintf("EKS cluster '%v' has no envelope encryption, so its Kubernetes Secrets sit in etcd without a KMS key in front of them.", [cluster.name]),
	}
}
