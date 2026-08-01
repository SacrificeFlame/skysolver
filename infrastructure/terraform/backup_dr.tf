resource "aws_backup_vault" "primary" {
  name        = "${local.prefix}-operational"
  kms_key_arn = aws_kms_key.platform.arn
}

resource "aws_kms_key" "dr" {
  count                   = var.enable_disaster_recovery ? 1 : 0
  provider                = aws.dr
  description             = "${local.prefix} disaster recovery encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}
resource "aws_backup_vault" "dr" {
  count       = var.enable_disaster_recovery ? 1 : 0
  provider    = aws.dr
  name        = "${local.prefix}-cross-region"
  kms_key_arn = aws_kms_key.dr[0].arn
}

resource "aws_backup_plan" "operational" {
  name = "${local.prefix}-operational"
  rule {
    rule_name         = "continuous-operational-backup"
    target_vault_name = aws_backup_vault.primary.name
    schedule          = "cron(0 */4 * * ? *)"
    start_window      = 60
    completion_window = 180
    lifecycle { delete_after = 35 }
    dynamic "copy_action" {
      for_each = var.enable_disaster_recovery ? [1] : []
      content {
        destination_vault_arn = aws_backup_vault.dr[0].arn
        lifecycle { delete_after = 35 }
      }
    }
  }
}

data "aws_iam_policy_document" "backup_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "backup" {
  name               = "${local.prefix}-backup"
  assume_role_policy = data.aws_iam_policy_document.backup_assume.json
}
resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}
resource "aws_backup_selection" "operational" {
  name         = "${local.prefix}-aurora"
  plan_id      = aws_backup_plan.operational.id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = [aws_rds_cluster.operational.arn]
}
