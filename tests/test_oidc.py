import time
from deployment.oidc import OidcTokenError,OidcVerifier


def test_verified_airline_claims_become_server_principal():
    now=int(time.time());verifier=OidcVerifier("https://idp.example","skysolver",lambda token:{"sub":"scheduler-7","exp":now+300,"auth_time":now,"tenant_id":"airline-1","skysolver_role":"scheduler","amr":["pwd","mfa"],"base":"DEL","stations":["DEL","BOM"]})
    principal=verifier.verify("signed")
    assert principal.subject=="scheduler-7" and principal.role=="scheduler" and principal.auth_method=="oidc"
    assert principal.amr==("pwd","mfa") and principal.stations==("DEL","BOM")


def test_unknown_role_or_missing_tenant_is_rejected():
    for claims in ({"sub":"x","exp":9999999999,"tenant_id":"a","role":"superadmin"},{"sub":"x","exp":9999999999,"role":"scheduler"}):
        try:OidcVerifier("https://idp.example","skysolver",lambda token,claims=claims:claims).verify("signed")
        except OidcTokenError:pass
        else:raise AssertionError("unsafe OIDC claims accepted")
