"""Tamper-evident legality certificates bound to immutable inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import uuid
from typing import Any


class CertificateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class LegalityCertificate:
    certificate_id: str
    tenant_id: str
    recovery_id: str
    candidate_id: str
    input_snapshot_sha256: str
    candidate_sha256: str
    rules_package_sha256: str
    ruleset_version: str
    state_version: int
    execution_identity: str
    validation_service_version: str
    validated_at: str
    valid: bool
    finding_count: int
    assurance_level: str
    signature: str
    signing_key_id: str

    def unsigned_payload(self):
        value = asdict(self); value.pop("signature")
        return value

    def to_dict(self):
        return asdict(self)


class CertificateIssuer:
    def __init__(self, signing_key_id: str, signing_key: bytes, execution_identity: str,
                 service_version: str, assurance_level: str):
        self.signing_key_id = signing_key_id
        self._key = signing_key
        self.execution_identity = execution_identity
        self.service_version = service_version
        self.assurance_level = assurance_level

    def issue(self, *, tenant_id: str, recovery_id: str, candidate_id: str, input_snapshot: Any,
              candidate: Any, rules_package: Any, ruleset_version: str, state_version: int,
              findings: list[dict]) -> LegalityCertificate:
        if findings:
            raise CertificateError("legality_findings", "A legality certificate cannot be issued with rule findings")
        unsigned = {
            "certificate_id": f"LGC-{uuid.uuid4().hex[:16].upper()}", "tenant_id": tenant_id,
            "recovery_id": recovery_id, "candidate_id": candidate_id,
            "input_snapshot_sha256": canonical_sha256(input_snapshot),
            "candidate_sha256": canonical_sha256(candidate), "rules_package_sha256": canonical_sha256(rules_package),
            "ruleset_version": ruleset_version, "state_version": state_version,
            "execution_identity": self.execution_identity, "validation_service_version": self.service_version,
            "validated_at": datetime.now(timezone.utc).isoformat(), "valid": True, "finding_count": 0,
            "assurance_level": self.assurance_level, "signing_key_id": self.signing_key_id,
        }
        signature = hmac.new(self._key, json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        return LegalityCertificate(**unsigned, signature=signature)

    def verify(self, certificate: LegalityCertificate, *, input_snapshot: Any, candidate: Any, rules_package: Any) -> bool:
        if certificate.input_snapshot_sha256 != canonical_sha256(input_snapshot): return False
        if certificate.candidate_sha256 != canonical_sha256(candidate): return False
        if certificate.rules_package_sha256 != canonical_sha256(rules_package): return False
        expected = hmac.new(self._key, json.dumps(certificate.unsigned_payload(), sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(certificate.signature, expected)
