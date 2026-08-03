import re
from pathlib import Path


ROOT=Path(__file__).parents[1]


def hcl(path:str)->str:
    """Read a Terraform file with attribute alignment collapsed.

    `terraform fmt -check` runs in CI, so column alignment is already
    guaranteed canonical and re-asserting it here only makes these tests break
    whenever an unrelated attribute in the same block changes width. Assert on
    the attribute and its value, not on the whitespace between them.
    """
    return re.sub(r"[ \t]*=[ \t]*"," = ",(ROOT/path).read_text())


EDGE=hcl("infrastructure/terraform/platform_edge.tf")
DR=(ROOT/"infrastructure/terraform/backup_dr.tf").read_text()
API=(ROOT/"deployment/k8s/api-deployment.yaml").read_text()


def test_edge_has_tls_waf_dns_and_private_target_group():
    assert 'protocol = "HTTPS"' in EDGE
    assert "ELBSecurityPolicy-TLS13" in EDGE
    assert "aws_wafv2_web_acl" in EDGE
    assert "AWSManagedRulesCommonRuleSet" in EDGE
    assert "rate_based_statement" in EDGE
    assert "aws_route53_record" in EDGE
    assert 'target_type = "ip"' in EDGE
    assert '/api/v1/health/ready' in EDGE


def test_workforce_federation_and_short_tokens_are_configured():
    assert "aws_cognito_identity_provider" in EDGE
    assert 'provider_type = "SAML"' in EDGE
    assert 'allowed_oauth_flows = ["code"]' in EDGE
    assert 'access_token_validity = 15' in EDGE


def test_backup_plan_has_optional_cross_region_copy():
    assert "aws_backup_plan" in DR
    assert "copy_action" in DR
    assert "aws_backup_vault.dr" in DR
    assert "aws_rds_cluster.operational.arn" in DR


def test_api_workload_is_fail_closed_non_root_and_read_only():
    assert "runAsNonRoot: true" in API
    assert "readOnlyRootFilesystem: true" in API
    assert "allowPrivilegeEscalation: false" in API
    assert "SKYSOLVER_ENABLE_CARRIER_WRITES, value: \"false\"" in API
    assert "SKYSOLVER_PERSISTENCE_BACKEND, value: aurora-postgresql" in API
    assert "@sha256:" in API and ":latest" not in API
