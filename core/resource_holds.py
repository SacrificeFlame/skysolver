"""Atomic, expiring resource holds for candidate review."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import threading
import uuid
from typing import Callable


class HoldConflict(Exception):
    def __init__(self, code: str, message: str, resources: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.resources = resources or []


@dataclass(frozen=True)
class ResourceHold:
    hold_id: str
    tenant_id: str
    recovery_id: str
    candidate_id: str
    candidate_version: int
    resources: tuple[str, ...]
    owner: str
    acquired_at: datetime
    expires_at: datetime

    def to_dict(self):
        value = asdict(self)
        value["resources"] = list(self.resources)
        value["acquired_at"] = self.acquired_at.isoformat()
        value["expires_at"] = self.expires_at.isoformat()
        return value


class ResourceHoldRegistry:
    def __init__(self, clock: Callable[[], datetime] | None = None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._holds: dict[str, ResourceHold] = {}
        self._resource_index: dict[tuple[str, str], str] = {}

    def _expire(self):
        current = self._clock()
        for hold_id, hold in list(self._holds.items()):
            if hold.expires_at <= current:
                self._release(hold_id)

    def _release(self, hold_id: str):
        hold = self._holds.pop(hold_id, None)
        if hold:
            for resource in hold.resources:
                self._resource_index.pop((hold.tenant_id, resource), None)

    def acquire(self, *, tenant_id: str, recovery_id: str, candidate_id: str, candidate_version: int,
                resources: list[str], owner: str, ttl_seconds: int = 600) -> ResourceHold:
        if ttl_seconds < 30 or ttl_seconds > 1800:
            raise HoldConflict("invalid_hold_ttl", "Hold TTL must be between 30 and 1800 seconds")
        normalized = tuple(sorted(set(resources)))
        if not normalized:
            raise HoldConflict("resources_required", "Candidate hold requires resources")
        with self._lock:
            self._expire()
            conflicts = [resource for resource in normalized if (tenant_id, resource) in self._resource_index]
            if conflicts:
                raise HoldConflict("resource_conflict", "One or more resources are already held", conflicts)
            acquired = self._clock()
            hold = ResourceHold(f"HLD-{uuid.uuid4().hex[:12].upper()}", tenant_id, recovery_id, candidate_id,
                                candidate_version, normalized, owner, acquired, acquired + timedelta(seconds=ttl_seconds))
            self._holds[hold.hold_id] = hold
            for resource in normalized:
                self._resource_index[(tenant_id, resource)] = hold.hold_id
            return hold

    def get(self, hold_id: str) -> ResourceHold:
        with self._lock:
            self._expire()
            try:
                return self._holds[hold_id]
            except KeyError as exc:
                raise HoldConflict("hold_expired_or_missing", "Resource hold is missing or expired") from exc

    def assert_current(self, hold_id: str, candidate_id: str, candidate_version: int) -> ResourceHold:
        hold = self.get(hold_id)
        if hold.candidate_id != candidate_id or hold.candidate_version != candidate_version:
            raise HoldConflict("stale_hold", "Resource hold does not match the candidate version")
        return hold

    def release(self, hold_id: str, owner: str):
        with self._lock:
            hold = self.get(hold_id)
            if hold.owner != owner:
                raise HoldConflict("hold_owner_mismatch", "Only the hold owner can release it")
            self._release(hold_id)

    def release_for_recovery(self, hold_id: str, recovery_id: str):
        """Server-side release after an authorized recovery transition."""
        with self._lock:
            hold = self.get(hold_id)
            if hold.recovery_id != recovery_id:
                raise HoldConflict("hold_recovery_mismatch", "Hold belongs to another recovery")
            self._release(hold_id)

    def release_all_for_recovery(self, recovery_id: str) -> list[str]:
        """Release every hold a recovery still owns.

        Used when a recovery is superseded: its holds must not outlive it, or
        the resources it reserved stay locked and no later recovery can ever
        select a candidate that needs them.
        """
        with self._lock:
            self._expire()
            hold_ids = [hid for hid, hold in self._holds.items() if hold.recovery_id == recovery_id]
            for hold_id in hold_ids:
                self._release(hold_id)
            return hold_ids
