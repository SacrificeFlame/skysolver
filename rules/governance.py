"""Effective-dated rules-package governance and activation controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import json
import threading
import uuid
from typing import Any


class RulePackageStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SHADOW = "shadow"
    ACTIVE = "active"
    RETIRED = "retired"
    REJECTED = "rejected"


class GovernanceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RuleApproval:
    approval_id: str
    actor: str
    authority: str
    reason: str
    approved_at: datetime


@dataclass(frozen=True)
class ShadowEvidence:
    evidence_id: str
    cases_evaluated: int
    expected_matches: int
    unexpected_differences: int
    blocking_findings: int
    artifact_sha256: str
    recorded_at: datetime


@dataclass
class RulePackage:
    package_id: str
    tenant_id: str
    version: str
    effective_from: datetime
    effective_until: datetime | None
    submitted_by: str
    content: dict[str, Any]
    content_sha256: str
    signature: str
    signing_key_id: str
    status: RulePackageStatus = RulePackageStatus.DRAFT
    approvals: list[RuleApproval] = field(default_factory=list)
    shadow_evidence: ShadowEvidence | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        value = asdict(self); value["status"] = self.status.value
        return value


class RulePackageRegistry:
    REQUIRED_AUTHORITIES = {"airline-operations", "regulatory-compliance"}

    def __init__(self, signing_keys: dict[str, bytes]):
        self._keys = signing_keys
        self._packages: dict[str, RulePackage] = {}
        self._active_by_tenant: dict[str, str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def canonical_content(content: dict[str, Any]) -> bytes:
        return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

    @classmethod
    def sign(cls, content: dict[str, Any], key: bytes) -> str:
        return hmac.new(key, cls.canonical_content(content), hashlib.sha256).hexdigest()

    def submit(self, *, tenant_id: str, version: str, effective_from: datetime, effective_until: datetime | None,
               submitted_by: str, content: dict[str, Any], signature: str, signing_key_id: str) -> RulePackage:
        if effective_from.tzinfo is None or (effective_until and effective_until.tzinfo is None):
            raise GovernanceError("timezone_required", "Rules effective dates must be timezone-aware")
        if effective_until and effective_until <= effective_from:
            raise GovernanceError("invalid_effective_period", "Rules effective period must be positive")
        key = self._keys.get(signing_key_id)
        if key is None:
            raise GovernanceError("unknown_signing_key", "Rules package signing key is not trusted")
        expected = self.sign(content, key)
        if not hmac.compare_digest(signature, expected):
            raise GovernanceError("invalid_signature", "Rules package signature verification failed")
        digest = hashlib.sha256(self.canonical_content(content)).hexdigest()
        with self._lock:
            if any(item.tenant_id == tenant_id and item.version == version for item in self._packages.values()):
                raise GovernanceError("version_exists", "Ruleset version already exists for tenant")
            package = RulePackage(f"RPK-{uuid.uuid4().hex[:12].upper()}", tenant_id, version, effective_from,
                                  effective_until, submitted_by, content, digest, signature, signing_key_id)
            self._packages[package.package_id] = package
            return package

    def approve(self, package_id: str, actor: str, authority: str, reason: str) -> RulePackage:
        with self._lock:
            package = self.get(package_id)
            if package.status not in {RulePackageStatus.DRAFT, RulePackageStatus.APPROVED}:
                raise GovernanceError("invalid_status", "Only draft packages can receive approvals")
            if actor == package.submitted_by:
                raise GovernanceError("four_eyes_required", "Submitter cannot approve their own rules package")
            if authority not in self.REQUIRED_AUTHORITIES:
                raise GovernanceError("invalid_authority", "Approval authority is not recognized")
            if any(item.actor == actor or item.authority == authority for item in package.approvals):
                raise GovernanceError("duplicate_approval", "Approval actor and authority must be independent")
            if not reason.strip():
                raise GovernanceError("reason_required", "Rule approval requires a reason")
            package.approvals.append(RuleApproval(str(uuid.uuid4()), actor, authority, reason.strip(), datetime.now(timezone.utc)))
            if {item.authority for item in package.approvals} == self.REQUIRED_AUTHORITIES:
                package.status = RulePackageStatus.APPROVED
            return package

    def begin_shadow(self, package_id: str) -> RulePackage:
        with self._lock:
            package = self.get(package_id)
            if package.status is not RulePackageStatus.APPROVED:
                raise GovernanceError("approvals_required", "Both airline and regulatory approvals are required")
            package.status = RulePackageStatus.SHADOW
            return package

    def record_shadow(self, package_id: str, *, cases_evaluated: int, expected_matches: int,
                      unexpected_differences: int, blocking_findings: int, artifact_sha256: str) -> RulePackage:
        with self._lock:
            package = self.get(package_id)
            if package.status is not RulePackageStatus.SHADOW:
                raise GovernanceError("shadow_not_active", "Package must enter shadow evaluation first")
            if cases_evaluated <= 0 or expected_matches + unexpected_differences != cases_evaluated:
                raise GovernanceError("invalid_shadow_evidence", "Shadow counts are inconsistent")
            if len(artifact_sha256) != 64:
                raise GovernanceError("invalid_artifact_digest", "Shadow artifact requires a SHA-256 digest")
            package.shadow_evidence = ShadowEvidence(str(uuid.uuid4()), cases_evaluated, expected_matches,
                                                     unexpected_differences, blocking_findings, artifact_sha256,
                                                     datetime.now(timezone.utc))
            return package

    def activate(self, package_id: str, at: datetime | None = None) -> RulePackage:
        with self._lock:
            package = self.get(package_id); current = at or datetime.now(timezone.utc)
            evidence = package.shadow_evidence
            if package.status is not RulePackageStatus.SHADOW or evidence is None:
                raise GovernanceError("shadow_evidence_required", "Passing shadow evidence is required")
            if evidence.unexpected_differences or evidence.blocking_findings:
                raise GovernanceError("shadow_gate_failed", "Unexpected differences or blocking findings prevent activation")
            if current < package.effective_from or (package.effective_until and current >= package.effective_until):
                raise GovernanceError("outside_effective_period", "Rules package is not effective at activation time")
            previous_id = self._active_by_tenant.get(package.tenant_id)
            if previous_id:
                self._packages[previous_id].status = RulePackageStatus.RETIRED
            package.status = RulePackageStatus.ACTIVE
            self._active_by_tenant[package.tenant_id] = package.package_id
            return package

    def rollback(self, tenant_id: str, target_package_id: str) -> RulePackage:
        with self._lock:
            target = self.get(target_package_id)
            if target.tenant_id != tenant_id or target.status is not RulePackageStatus.RETIRED:
                raise GovernanceError("rollback_target_invalid", "Rollback target must be a retired package for the tenant")
            current_id = self._active_by_tenant.get(tenant_id)
            if current_id:
                self._packages[current_id].status = RulePackageStatus.RETIRED
            target.status = RulePackageStatus.ACTIVE
            self._active_by_tenant[tenant_id] = target.package_id
            return target

    def active(self, tenant_id: str) -> RulePackage:
        package_id = self._active_by_tenant.get(tenant_id)
        if not package_id:
            raise GovernanceError("no_active_ruleset", "Tenant has no active rules package")
        return self._packages[package_id]

    def get(self, package_id: str) -> RulePackage:
        try:
            return self._packages[package_id]
        except KeyError as exc:
            raise GovernanceError("package_not_found", "Rules package not found") from exc
