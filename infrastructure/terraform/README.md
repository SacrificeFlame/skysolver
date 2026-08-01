# AWS production foundation

This Terraform root defines the three-AZ VPC, private EKS control/data plane,
Aurora PostgreSQL, IAM-authenticated MSK, encrypted Redis coordination, Object
Locked S3 artifacts, KMS, immutable ECR repositories, Secrets Manager and the
Cognito workforce boundary.

It is intentionally not applied automatically. Account IDs, approved engine
versions, federation metadata, WAF/ALB policy, Route 53 zones, DR region and
cost limits are airline-specific release inputs. The baseline validates
`carrier_writes_enabled == false`; controlled publishing must use a separately
reviewed overlay and policy exemption after the shadow-pilot exit gate.

Before plan/apply:

1. Pin the module/provider lock file in an approved build environment.
2. Replace the Kubernetes image digest sentinel through signed CI promotion.
3. Supply remote encrypted state with DynamoDB locking.
4. Complete the airline threat model and network allow-list.
5. Run `terraform fmt`, `terraform validate`, Checkov/OPA policy and a reviewed plan.
