locals {
  edge_enabled   = var.public_edge_enabled && var.hosted_zone_id != "" && var.dashboard_hostname != "" && var.acm_certificate_arn != ""
  cognito_domain = var.cognito_domain_prefix != "" ? var.cognito_domain_prefix : "${local.prefix}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_security_group" "edge" {
  count       = local.edge_enabled ? 1 : 0
  name        = "${local.prefix}-edge"
  description = "TLS ingress to the SkySolver API edge"
  vpc_id      = module.vpc.vpc_id
  ingress {
    description      = "HTTPS"
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
  egress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_lb" "api" {
  count                      = local.edge_enabled ? 1 : 0
  name                       = substr("${local.prefix}-api", 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.edge[0].id]
  subnets                    = module.vpc.public_subnets
  enable_deletion_protection = true
  drop_invalid_header_fields = true
  access_logs {
    bucket  = aws_s3_bucket.access_logs[0].id
    enabled = true
  }
  depends_on = [aws_s3_bucket_policy.access_logs]
}

resource "aws_s3_bucket" "access_logs" {
  count  = local.edge_enabled ? 1 : 0
  bucket = "${local.prefix}-${data.aws_caller_identity.current.account_id}-access-logs"
}
resource "aws_s3_bucket_public_access_block" "access_logs" {
  count                   = local.edge_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.access_logs[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  count  = local.edge_enabled ? 1 : 0
  bucket = aws_s3_bucket.access_logs[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  count  = local.edge_enabled ? 1 : 0
  bucket = aws_s3_bucket.access_logs[0].id
  rule {
    id     = "retain-operational-access-logs"
    status = "Enabled"
    expiration { days = 400 }
  }
}
data "aws_iam_policy_document" "access_logs" {
  count = local.edge_enabled ? 1 : 0
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs[0].arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }
  }
  statement {
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.access_logs[0].arn]
    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }
  }
}
resource "aws_s3_bucket_policy" "access_logs" {
  count  = local.edge_enabled ? 1 : 0
  bucket = aws_s3_bucket.access_logs[0].id
  policy = data.aws_iam_policy_document.access_logs[0].json
}

resource "aws_lb_target_group" "api" {
  count                = local.edge_enabled ? 1 : 0
  name                 = substr("${local.prefix}-api", 0, 32)
  port                 = 8080
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = module.vpc.vpc_id
  deregistration_delay = 60
  health_check {
    enabled             = true
    path                = "/api/v1/health/ready"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  count             = local.edge_enabled ? 1 : 0
  load_balancer_arn = aws_lb.api[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}

resource "aws_wafv2_web_acl" "api" {
  count = local.edge_enabled ? 1 : 0
  name  = "${local.prefix}-api"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.prefix}-waf"
    sampled_requests_enabled   = true
  }
  rule {
    name     = "AWSManagedCommon"
    priority = 10
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "common"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "AWSManagedKnownBadInputs"
    priority = 20
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "known-bad"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "RateLimit"
    priority = 30
    action {
      block {}
    }
    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = 2000
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }
}
resource "aws_wafv2_web_acl_association" "api" {
  count        = local.edge_enabled ? 1 : 0
  resource_arn = aws_lb.api[0].arn
  web_acl_arn  = aws_wafv2_web_acl.api[0].arn
}
resource "aws_route53_record" "api" {
  count   = local.edge_enabled ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = var.dashboard_hostname
  type    = "A"
  alias {
    name                   = aws_lb.api[0].dns_name
    zone_id                = aws_lb.api[0].zone_id
    evaluate_target_health = true
  }
}

resource "aws_cognito_identity_provider" "airline_saml" {
  count             = var.saml_metadata_url != "" ? 1 : 0
  user_pool_id      = aws_cognito_user_pool.workforce.id
  provider_name     = var.saml_idp_name
  provider_type     = "SAML"
  provider_details  = { MetadataURL = var.saml_metadata_url, IDPSignout = "true" }
  attribute_mapping = { email = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress" }
}
resource "aws_cognito_user_pool_domain" "workforce" {
  domain       = local.cognito_domain
  user_pool_id = aws_cognito_user_pool.workforce.id
}
resource "aws_cognito_user_pool_client" "workforce" {
  name                                 = "${local.prefix}-occ"
  user_pool_id                         = aws_cognito_user_pool.workforce.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = var.saml_metadata_url != "" ? [aws_cognito_identity_provider.airline_saml[0].provider_name] : ["COGNITO"]
  callback_urls                        = local.edge_enabled ? ["https://${var.dashboard_hostname}/auth/callback"] : ["https://localhost.invalid/auth/callback"]
  logout_urls                          = local.edge_enabled ? ["https://${var.dashboard_hostname}/logout"] : ["https://localhost.invalid/logout"]
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
  prevent_user_existence_errors = "ENABLED"
}

resource "aws_prometheus_workspace" "platform" {
  alias = local.prefix
}
resource "aws_cloudwatch_log_group" "application" {
  name              = "/skysolver/${local.prefix}/application"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.platform.arn
}
resource "aws_cloudwatch_log_group" "audit" {
  name = "/skysolver/${local.prefix}/audit"
  # CloudWatch only accepts a fixed set of retention values; 2555 (the literal
  # 7 x 365) is not one of them. 2557 is the API's seven-year constant.
  retention_in_days = 2557
  kms_key_id        = aws_kms_key.platform.arn
}

resource "aws_cloudwatch_metric_alarm" "aurora_cpu" {
  alarm_name          = "${local.prefix}-aurora-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = 80
  dimensions          = { DBClusterIdentifier = aws_rds_cluster.operational.cluster_identifier }
  alarm_actions       = var.alarm_topic_arn == "" ? [] : [var.alarm_topic_arn]
}
