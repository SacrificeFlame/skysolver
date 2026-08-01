"""Enterprise OIDC bearer validation and airline-claim mapping."""

from __future__ import annotations

import json
import os
from typing import Any,Callable

from deployment.auth import Principal
from deployment.authorization import Role


class OidcConfigurationError(RuntimeError):pass
class OidcTokenError(ValueError):pass


class OidcVerifier:
    def __init__(self,issuer:str,audience:str,decode:Callable[[str],dict[str,Any]]):
        if not issuer.startswith("https://") or not audience:raise OidcConfigurationError("OIDC issuer and audience are required")
        self.issuer=issuer.rstrip("/");self.audience=audience;self._decode=decode
    def verify(self,token:str)->Principal:
        try:claims=self._decode(token)
        except Exception as exc:raise OidcTokenError("Bearer token verification failed") from exc
        required=("sub","exp","tenant_id")
        if any(not claims.get(key) for key in required):raise OidcTokenError("OIDC token is missing required airline claims")
        role=str(claims.get("skysolver_role") or claims.get("role") or "")
        try:Role(role)
        except ValueError as exc:raise OidcTokenError("OIDC role is not mapped to SkySolver") from exc
        amr=claims.get("amr") or []
        if isinstance(amr,str):amr=[amr]
        stations=claims.get("stations") or []
        if isinstance(stations,str):stations=[stations]
        return Principal(str(claims["sub"]),role,str(claims["tenant_id"]),int(claims["exp"]),"oidc",int(claims.get("auth_time",0)),tuple(map(str,amr)),claims.get("base"),tuple(map(str,stations)))


def configured_verifier()->OidcVerifier:
    issuer=os.environ.get("SKYSOLVER_OIDC_ISSUER","");audience=os.environ.get("SKYSOLVER_OIDC_AUDIENCE","")
    try:
        import jwt
        client=jwt.PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json")
    except Exception as exc:raise OidcConfigurationError("PyJWT OIDC support is unavailable") from exc
    def decode(token):
        key=client.get_signing_key_from_jwt(token).key
        return jwt.decode(token,key,algorithms=["RS256"],audience=audience,issuer=issuer,options={"require":["exp","iat","sub"]})
    return OidcVerifier(issuer,audience,decode)
