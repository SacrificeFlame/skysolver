output "eks_cluster_name" { value = module.eks.cluster_name }
output "aurora_writer_endpoint" {
  value     = aws_rds_cluster.operational.endpoint
  sensitive = true
}
output "msk_bootstrap_brokers_sasl_iam" {
  value     = aws_msk_cluster.events.bootstrap_brokers_sasl_iam
  sensitive = true
}
output "artifact_bucket" { value = aws_s3_bucket.artifacts.id }
output "cognito_user_pool_id" { value = aws_cognito_user_pool.workforce.id }
output "carrier_writes_enabled" { value = var.carrier_writes_enabled }
output "api_target_group_arn" { value = local.edge_enabled ? aws_lb_target_group.api[0].arn : null }
output "dashboard_url" { value = local.edge_enabled ? "https://${var.dashboard_hostname}/dashboard" : null }
output "prometheus_workspace_arn" { value = aws_prometheus_workspace.platform.arn }
output "cognito_client_id" { value = aws_cognito_user_pool_client.workforce.id }
output "dr_backup_vault_arn" { value = var.enable_disaster_recovery ? aws_backup_vault.dr[0].arn : null }
