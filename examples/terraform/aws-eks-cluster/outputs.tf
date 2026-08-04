output "cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "cluster_name" {
  description = "Name of the EKS cluster, for kubeconfig generation."
  value       = aws_eks_cluster.main.name
}
