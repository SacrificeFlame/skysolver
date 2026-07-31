"""Canonical recovery-domain contracts shared by APIs, solvers and audit logs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class RuleViolation:
    code: str
    message: str
    rule_ref: str
    severity: Severity = Severity.ERROR
    entity_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def __contains__(self, value: str) -> bool:
        """Keep legacy ``'text' in violation`` callers source-compatible."""
        return value in self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "rule_ref": self.rule_ref,
            "severity": self.severity.value,
            "entity_id": self.entity_id,
            "details": self.details,
        }


class RecoveryTier(str, Enum):
    HEURISTIC = "tier1"
    OPTIMIZER = "tier2"
    HUMAN_ASSIST = "tier3"


@dataclass(frozen=True)
class AuditMetadata:
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    causation_id: str | None = None
    ruleset_version: str = "synthetic-far117-v2"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RecoveryOutcome:
    partition_id: str
    tier: RecoveryTier
    assignments: list[Any]
    uncovered: list[Any]
    elapsed_s: float
    complete: bool
    reason: str
    audit: AuditMetadata = field(default_factory=AuditMetadata)

    @property
    def coverage(self) -> float:
        total = sum(len(a.flight_legs) for a in self.assignments) + len(self.uncovered)
        covered = total - len(self.uncovered)
        return covered / total if total else 1.0
