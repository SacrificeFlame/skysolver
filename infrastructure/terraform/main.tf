data "aws_availability_zones" "available" { state = "available" }
data "aws_caller_identity" "current" {}

locals {
  prefix = "${var.name}-${var.environment}"
  azs    = slice(data.aws_availability_zones.available.names, 0, 3)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name             = local.prefix
  cidr             = var.vpc_cidr
  azs              = local.azs
  private_subnets  = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, index)]
  database_subnets = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, index + 4)]
  intra_subnets    = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, index + 8)]
  public_subnets   = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, index + 12)]

  enable_nat_gateway           = true
  one_nat_gateway_per_az       = true
  enable_dns_hostnames         = true
  enable_dns_support           = true
  create_database_subnet_group = true
  private_subnet_tags          = { "kubernetes.io/role/internal-elb" = "1" }
  public_subnet_tags           = { "kubernetes.io/role/elb" = "1" }
}

resource "aws_kms_key" "platform" {
  description             = "${local.prefix} platform encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}
resource "aws_kms_alias" "platform" {
  name          = "alias/${local.prefix}"
  target_key_id = aws_kms_key.platform.key_id
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name                    = local.prefix
  cluster_version                 = var.kubernetes_version
  cluster_endpoint_public_access  = false
  cluster_endpoint_private_access = true
  cluster_enabled_log_types       = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  cluster_encryption_config       = { provider_key_arn = aws_kms_key.platform.arn, resources = ["secrets"] }
  enable_irsa                     = true
  vpc_id                          = module.vpc.vpc_id
  subnet_ids                      = module.vpc.private_subnets
  control_plane_subnet_ids        = module.vpc.intra_subnets

  eks_managed_node_groups = {
    system = {
      instance_types = ["m7i.large"]
      min_size       = 3
      max_size       = 9
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      labels         = { workload = "system" }
    }
    solver = {
      instance_types = ["c7i.2xlarge", "c7a.2xlarge"]
      min_size       = 0
      max_size       = 100
      desired_size   = 0
      capacity_type  = "SPOT"
      labels         = { workload = "solver" }
      taints         = { solver = { key = "skysolver.io/solver", value = "true", effect = "NO_SCHEDULE" } }
    }
  }
}

resource "aws_security_group" "data" {
  name   = "${local.prefix}-data"
  vpc_id = module.vpc.vpc_id
  ingress {
    description     = "EKS data-plane access"
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_rds_cluster" "operational" {
  cluster_identifier              = "${local.prefix}-aurora"
  engine                          = "aurora-postgresql"
  engine_mode                     = "provisioned"
  database_name                   = var.database_name
  master_username                 = var.database_master_username
  manage_master_user_password     = true
  db_subnet_group_name            = module.vpc.database_subnet_group_name
  vpc_security_group_ids          = [aws_security_group.data.id]
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.platform.arn
  backup_retention_period         = 35
  preferred_backup_window         = "18:30-19:30"
  deletion_protection             = true
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
  serverlessv2_scaling_configuration {
    min_capacity = 2
    max_capacity = 64
  }
  lifecycle { prevent_destroy = true }
}

resource "aws_rds_cluster_instance" "operational" {
  count              = 3
  identifier         = "${local.prefix}-aurora-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.operational.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.operational.engine
}

resource "aws_msk_cluster" "events" {
  cluster_name           = "${local.prefix}-events"
  kafka_version          = "3.7.x"
  number_of_broker_nodes = 3
  broker_node_group_info {
    instance_type   = "kafka.m7g.large"
    client_subnets  = module.vpc.private_subnets
    security_groups = [aws_security_group.data.id]
    storage_info {
      ebs_storage_info {
        volume_size = 1000
      }
    }
  }
  client_authentication {
    sasl {
      iam = true
    }
  }
  encryption_info {
    encryption_at_rest_kms_key_arn = aws_kms_key.platform.arn
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }
  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk.name
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "msk" {
  name              = "/aws/msk/${local.prefix}"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.platform.arn
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = local.prefix
  subnet_ids = module.vpc.database_subnets
}
resource "aws_elasticache_replication_group" "coordination" {
  replication_group_id       = "${local.prefix}-coordination"
  description                = "Short-lived coordination only; never authoritative state"
  node_type                  = "cache.r7g.large"
  port                       = 6379
  engine                     = "redis"
  num_cache_clusters         = 3
  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.data.id]
}

resource "aws_s3_bucket" "artifacts" {
  bucket              = "${local.prefix}-${data.aws_caller_identity.current.account_id}-artifacts"
  object_lock_enabled = true
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.platform.arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_object_lock_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = 2555
    }
  }
}
resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_ecr_repository" "services" {
  for_each             = toset(["api", "tier1", "tier2", "tier3", "rules", "validation", "adapter", "otel-collector"])
  name                 = "${local.prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.platform.arn
  }
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_secretsmanager_secret" "integration" {
  name                    = "${local.prefix}/integrations"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = 30
}

resource "aws_cognito_user_pool" "workforce" {
  name                = "${local.prefix}-workforce"
  deletion_protection = "ACTIVE"
  mfa_configuration   = "ON"
  software_token_mfa_configuration { enabled = true }
  user_pool_add_ons { advanced_security_mode = "ENFORCED" }
  password_policy {
    minimum_length                   = 16
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 1
  }
}
